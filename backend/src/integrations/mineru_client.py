"""MinerU Cloud OCR integration for handwritten answer images."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import os
import time
import zipfile
from pathlib import PurePosixPath
from typing import Any

import httpx


MAX_IMAGE_BYTES = 2_000_000
MAX_RESULT_ZIP_BYTES = 20_000_000
MAX_EXTRACTED_BYTES = 30_000_000
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MinerUError(RuntimeError):
    """Raised when MinerU cannot return a usable OCR result."""


class MinerUNotConfigured(MinerUError):
    """Raised when the deployment has no MinerU token."""


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def decode_image_data_url(data_url: str) -> tuple[bytes, str]:
    """Decode a browser image data URL and return bytes plus a safe suffix."""

    header, separator, encoded = data_url.partition(",")
    if not separator or not header.startswith("data:") or not header.endswith(";base64"):
        raise MinerUError("手写图片不是有效的 Base64 图片")
    mime_type = header[5:-7].lower()
    suffix = SUPPORTED_IMAGE_TYPES.get(mime_type)
    if suffix is None:
        raise MinerUError("手写图片仅支持 JPG、PNG 或 WebP")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MinerUError("手写图片 Base64 内容无效") from exc
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise MinerUError("手写图片为空或超过 2MB")
    signatures = {
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not signatures[suffix]:
        raise MinerUError("手写图片内容与文件类型不一致")
    return content, suffix


def _api_data(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise MinerUError("MinerU 返回了无法识别的响应")
    code = body.get("code", 0)
    if code != 0:
        message = str(body.get("msg") or "MinerU 请求失败")[:300]
        raise MinerUError(message)
    data = body.get("data")
    if not isinstance(data, dict):
        raise MinerUError("MinerU 响应缺少 data")
    return data


def _markdown_from_zip(zip_bytes: bytes) -> str:
    if not zip_bytes or len(zip_bytes) > MAX_RESULT_ZIP_BYTES:
        raise MinerUError("MinerU 结果文件为空或过大")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) > 200 or sum(item.file_size for item in files) > MAX_EXTRACTED_BYTES:
                raise MinerUError("MinerU 结果压缩包内容过大")
            markdown_files = [
                item for item in files if PurePosixPath(item.filename).suffix.lower() == ".md"
            ]
            if not markdown_files:
                raise MinerUError("MinerU 结果中没有识别文本")
            markdown_files.sort(key=lambda item: (len(item.filename), item.filename))
            return archive.read(markdown_files[0]).decode("utf-8", errors="replace").strip()
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU 结果压缩包损坏") from exc


class MinerUClient:
    """Minimal async client for MinerU's v4 file-upload extraction API."""

    def __init__(self) -> None:
        self.token = os.environ.get("MINERU_TOKEN", "").strip()
        if not self.token:
            raise MinerUNotConfigured("MINERU_TOKEN 未配置")
        self.base_url = os.environ.get("MINERU_BASE_URL", "https://mineru.net/api/v4").rstrip("/")
        configured_model = os.environ.get("MINERU_MODEL", "vlm").strip().lower()
        self.model = configured_model if configured_model in {"vlm", "pipeline"} else "vlm"
        self.total_timeout = _bounded_float_env("MINERU_TIMEOUT_SECONDS", 120, 15, 300)
        self.trust_env = os.environ.get("MINERU_USE_ENV_PROXY", "false").lower() == "true"

    async def extract_handwriting(self, image_data_url: str) -> str:
        image_bytes, suffix = decode_image_data_url(image_data_url)
        request_timeout = httpx.Timeout(30.0, read=min(self.total_timeout, 120.0), write=60.0)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "source": "psa-handwriting-ocr",
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=request_timeout,
            trust_env=self.trust_env,
        ) as client:
            upload_response = await client.post(
                "/file-urls/batch",
                json={
                    "files": [{"name": f"handwriting{suffix}", "is_ocr": True}],
                    "model_version": self.model,
                    "enable_formula": True,
                    "enable_table": False,
                    "language": "ch",
                },
            )
            upload_data = _api_data(upload_response)
            batch_id = str(upload_data.get("batch_id") or "")
            file_urls = upload_data.get("file_urls")
            if not batch_id or not isinstance(file_urls, list) or not file_urls:
                raise MinerUError("MinerU 没有返回图片上传地址")

            async with httpx.AsyncClient(timeout=request_timeout, trust_env=self.trust_env) as transfer:
                put_response = await transfer.put(str(file_urls[0]), content=image_bytes)
                put_response.raise_for_status()

            deadline = time.monotonic() + self.total_timeout
            delay = 1.0
            result_item: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                result_response = await client.get(f"/extract-results/batch/{batch_id}")
                result_data = _api_data(result_response)
                items = result_data.get("extract_result")
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    result_item = items[0]
                    state = str(result_item.get("state") or "").lower()
                    if state == "done":
                        break
                    if state == "failed":
                        detail = str(result_item.get("err_msg") or "图片识别失败")[:300]
                        raise MinerUError(detail)
                await asyncio.sleep(delay)
                delay = min(delay * 1.7, 8.0)
            else:
                raise MinerUError("MinerU 图片识别超时")

        zip_url = str((result_item or {}).get("full_zip_url") or "")
        if not zip_url:
            raise MinerUError("MinerU 结果缺少下载地址")
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
            trust_env=self.trust_env,
        ) as downloader:
            zip_response = await downloader.get(zip_url)
            zip_response.raise_for_status()
        markdown = _markdown_from_zip(zip_response.content)
        if not markdown:
            raise MinerUError("MinerU 未识别出可用内容")
        return markdown[:20_000]
