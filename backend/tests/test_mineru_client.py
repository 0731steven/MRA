import base64
import io
import zipfile

import pytest

from src.integrations.mineru_client import MinerUError, _markdown_from_zip, decode_image_data_url


def test_decode_image_data_url_accepts_supported_image():
    raw = b"\x89PNG\r\n\x1a\nsmall-image"
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode()

    content, suffix = decode_image_data_url(data_url)

    assert content == raw
    assert suffix == ".png"


def test_decode_image_data_url_rejects_fake_image_content():
    data_url = "data:image/png;base64," + base64.b64encode(b"not-a-png").decode()

    with pytest.raises(MinerUError, match="文件类型不一致"):
        decode_image_data_url(data_url)


def test_decode_image_data_url_rejects_unsupported_type():
    data_url = "data:image/gif;base64," + base64.b64encode(b"gif").decode()

    with pytest.raises(MinerUError, match="JPG、PNG 或 WebP"):
        decode_image_data_url(data_url)


def test_markdown_from_zip_returns_recognized_markdown():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("output/handwriting.md", "设 $X\\sim N(0,1)$")

    assert _markdown_from_zip(buffer.getvalue()) == "设 $X\\sim N(0,1)$"
