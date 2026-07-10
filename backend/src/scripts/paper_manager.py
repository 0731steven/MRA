#!/usr/bin/env python3
"""
IEEE Paper Manager (v2 - optimized)
- Scan ieee_papers/ directory and paper_meta.json
- Re-classify papers with updated CATS dictionary
- Deduplicate by docId (keep newest file)
- Move files to correct category folders
- Generate standalone HTML search/filter page

Performance optimizations (v2):
- Single fitz.open() per PDF (was 4-5 opens per file)
- File size limit to skip huge PDFs
- Memory-friendly batch processing with GC
- Progress reporting
- Cache to avoid redundant PDF parsing
"""

import os
import re
import json
import shutil
import html
import hashlib
import sys
import gc
import urllib.request
import urllib.error
import time

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

from pathlib import Path
from collections import defaultdict


def safe_print(msg):
    """Print with fallback for Windows GBK console."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', 'replace').decode('ascii'))


# ============================================================
# Performance settings
# ============================================================
MAX_PDF_SIZE_MB = 60          # Skip deep parsing for files larger than this
BATCH_SIZE = 50               # GC every N files
PROGRESS_INTERVAL = 20        # Print progress every N files

# ============================================================
# Configuration
# ============================================================
_SCRIPT_DIR = Path(__file__).resolve().parent

INPUT_DIRS_ENV = os.environ.get('IEEE_PAPER_DIRS', '')
if INPUT_DIRS_ENV:
    INPUT_DIRS = [Path(p.strip()) for p in INPUT_DIRS_ENV.split(';') if p.strip()]
else:
    INPUT_DIRS = [Path(os.path.expanduser("~/Downloads/ieee_papers"))]

BASE_DIR = INPUT_DIRS[0]
# Look for paper_meta.json: try BASE_DIR first, then scripts/ subdir
# Prefer the largest paper_meta.json (scripts/ has the master copy)
_META_CANDIDATES = [_SCRIPT_DIR / "paper_meta.json", BASE_DIR / "paper_meta.json"]
_META_FILES = [p for p in _META_CANDIDATES if p.exists()]
if _META_FILES:
    META_FILE = max(_META_FILES, key=lambda p: p.stat().st_size)
else:
    META_FILE = _META_CANDIDATES[0]
HTML_FILE = BASE_DIR / "index.html"
BACKUP_DIR = BASE_DIR / "_duplicates"

MANUAL_REVIEW = []
IMPORTED_FOLDERS = []

IEEE_BASE_URL = "https://ieeexplore.ieee.org/document/"

# ============================================================
# CATS dictionary  (must match chrome extension content.js)
# ============================================================
CATS = {
    'ADC': ['adc','analog-to-digital','a/d converter','a/d conversion','sar ','pipeline adc','pipelined','delta-sigma','sigma-delta','noise-shaping','noise shaping','subranging','zoom adc','flash adc','successive approximation','time-interleaved','ti-adc','ti adc','ti-sar','oversampling adc','incremental adc','ns-sar','vco-based adc','vco adc','ring-amp','quantizer','lock-in adc','touch-sensing','ctdsm'],
    'DAC': ['dac','digital-to-analog','d/a converter','d/a conversion','current-steering','current-mode dac','r-2r','r2r','r-dac','segmented dac','audio dac','rf dac','resistor-string'],
    'Amplifier': ['amplifier','lna','low-noise amplifier','power amplifier','pa ','transmitter','op-amp','opamp','vga','variable gain','transconductance','ota ','operational transconductance','operational amplifier','class-d','class-ab','class d ','class ab ','chopper amplifier','chopper-stabilized','gain boost'],
    'AFE': ['analog front-end','analog front end','sensor front end','sensor front-end','readout front end','readout front-end','sensor readout','instrumentation amplifier','in-amp','pga','programmable gain','afe ','readout circuit','readout ic','signal conditioning','capacitance-to-digital','cdc '],
    'PLL': ['pll','phase-locked','vco ','voltage-controlled oscillator','clock multiplier','frequency synthesizer','injection-locked','ring oscillator','lc oscillator','dpll','adpll','all-digital pll','fractional-n','integer-n','sub-sampling pll','ss-pll','sspll','mdll','cppll','dco ','digitally controlled oscillator','fll ','frequency-locked','bang-bang pd','bbpd','charge-pump pll','phase noise','injection locking','oscillator pulling'],
    'Clocking': ['clock distribution','clock buffer','clock tree','delay-locked','dll','clock generator','jitter clean','duty cycle correct','multiphase clock','deskew','clock synthesis','low-jitter clock','crystal oscillator','xtal ','rc oscillator','rc frequency'],
    'Power': ['power management','pmic','ldo','low-dropout','dc-dc','dcdc','dc/dc','buck ','boost ','buck-boost','flyback','rectifier','regulator','energy harvesting','ac-dc','ac/dc','charge pump','switched-capacitor converter','switched-capacitor regulator','sc converter','sc power','simo','sido','wireless power','power converter','power supply','resonant converter','hybrid converter','dickson','capacitive converter','voltage regulator','voltage converter','linear regulator','switching regulator','voltage doubler','step-down','step-up','inductive converter','pmu ','power stage','gate driver','battery charger','scvr','dc-dc converter','bidirectional converter','zvs','zcs','dead-time control','isolated converter','isolated dc','flying capacitor','multilevel','llc converter','llc resonant','current-mode control','current mode control','led driver','cell balancing','charge balancing','smart power','power electronics','power semiconductor','gallium nitride','gan power','switched tank','gate drive','nanopower','power ic','power oscillator'],
    'RF': ['rf ','radio frequency','mmwave','mm-wave','millimeter','wireless','transceiver','receiver','phased-array','phased array','beamforming','antenna','mixer','modulator','rfic','up-converter','down-converter','up-conversion','down-conversion','direct-conversion','5g ','local oscillator','n-path','wlan','wifi','wi-fi','uwb ','bluetooth','nb-iot','duplexer','heterodyne','homodyne','iq ','i/q '],
    'Radar': ['radar','fmcw','doppler','mimo radar','chirp','automotive radar','77 ghz','77-ghz','79 ghz','79-ghz','gesture radar','vital sign','ranging radar'],
    'mmWave_THz': ['thz','terahertz','beyond 100ghz','sub-thz','300 ghz','300-ghz','200 ghz','140 ghz','w-band','d-band','g-band','120 ghz','240 ghz','160 ghz'],
    'Wireline': ['serdes','serializer','deserializer','equalizer','cdr','clock data recovery','die-to-die','optical','photonic','transimpedance','pam4','pam-4','pam 4','nrz ','high-speed link','laser driver','vcsel','retimer','phy ','ethernet','pcie','usb ','displayport','hdmi','serial link','gearbox'],
    'SRAM': ['sram','static ram','register file','bitcell','bit-cell','6t ','8t ','10t ','sram macro','sram array'],
    'Memory': ['dram','flash memory','nand','reram','mram','stt-mram','ferroelectric','non-volatile memory','nvm ','nvram','pcram','pcm ','phase-change memory','sot-mram','embedded flash','eflash','nor flash','emerging memory','oxide ram','spin-orbit torque','sense amplifier'],
    'CIM': ['cim','computing-in-memory','compute-in-memory','in-memory computing','processing-in-memory','pim ','near-memory computing','in-sram computing','analog computing','mac array','crossbar array','memristive computing'],
    'Image_Sensor': ['image sensor','cmos imager','pixel sensor','camera','vision sensor','cmos image','dynamic vision','dvs ','event camera','global shutter','rolling shutter','stacked image','backside-illuminated','bsi ','quanta image'],
    'Bio_Sensor': ['biosensor','bio-sensor','ecg','eeg','neural recording','neural interface','implantable','wearable sensor','neuromodulation','emg','ppg','exg','biopotential','brain-computer','bci ','cortical','neural stimulat','glucose sensor','bioimpedance','body area network','neuroprosthetic','neural probe','biomedical','intracranial'],
    'LiDAR_ToF': ['lidar','tof ','time-of-flight','time of flight','spad','single-photon','depth sensor','dtof','itof','flash lidar','sipm ','photon counting','avalanche photodiode','apd ','3d imaging','range finder','geiger mode'],
    'Env_Sensor': ['temperature sensor','pressure sensor','gas sensor','humidity','accelerometer','gyroscope','mems sensor','thermal sensor','thermometer','inertial sensor','imu ','inertial measurement','magnetic sensor','hall sensor','ph sensor','chemical sensor','flow sensor','ultrasonic sensor','mems'],
    'AI_Accelerator': ['neural network','deep learning','cnn ','transformer','inference','training accelerator','tensor','npu ','llm','machine learning','ml accelerator','rnn ','lstm','spiking neural','snn ','neuromorphic','edge ai','tinyml','dnn ','binary neural','ternary neural','systolic','dataflow accelerator'],
    'DSP': ['dsp ','digital signal processing','fft ','filter bank','cordic','fir ','iir ','decimation filter','interpolation filter','baseband processor','modem','digital filter'],
    'Quantum': ['quantum','qubit','cryogenic','cryo-cmos','superconducting','dilution refrigerator','millikelvin','4k cmos','single flux quantum','josephson','transmon','squid '],
    'Security': ['puf','physically unclonable','trng','true random','hardware security','encryption','aes ','cipher','side-channel','fault attack','tamper','crypto','anti-counterfeit','obfuscation','logic locking'],
    'Comparator': ['comparator','dynamic comparator','strongarm','double-tail'],
    'Reference': ['bandgap','voltage reference','current reference','bgr ','bias generator','curvature compensat'],
    'Filter': ['active filter','switched-capacitor filter','gm-c filter','continuous-time filter','anti-aliasing','bandpass filter','lowpass filter','highpass filter','notch filter','biquad','reconfigurable filter','tunable filter','analog filter','channel filter','baseband filter'],
    'Packaging': ['3d ic','2.5d','chiplet','heterogeneous integration','fan-out','system-in-package','tsv','through-silicon','advanced packaging','wafer-level','interposer','micro-bump','hybrid bonding','monolithic 3d','ucie','redistribution layer','dicing','qfn ','wlcsp','wcsp','solder joint','chip scale package','plastic-encapsulated','wire bond','wire-bond','power module','passivation crack'],
    'Process_Technology': ['finfet','gate-all-around','gaa ','nanosheet','nanowire','fd-soi','7nm','5nm','3nm','2nm','cfet','complementary fet','bulk cmos','ldmos','bcd process','bcd technology','deep trench','locos','damascene','efuse','e-fuse','field plate','hot carrier'],
}

# Patent detection regex patterns (US and CN patents)
_PATENT_RE = re.compile(
    r'US\d{7,11}|US\d{4}/\d{7}|US\d{11}[AB]\d'
    r'|CN\d{9,12}[AB]?'
    r'|patent|utility model|apparatus and method|apparatus and control',
    re.IGNORECASE,
)

STD_CATEGORIES = set(CATS.keys()) | {'Others', '_duplicates', 'Patent'}


def _normalize_tag(t):
    t = t.strip().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def _split_parentheses(t):
    """Split 'Analog-to-Digital Converter (ADC)' into ['Analog-to-Digital Converter', 'ADC']."""
    parts = []
    t = t.strip()
    m = re.search(r"^(.+?)\s*\(([^)]+)\)\s*$", t)
    if m:
        base, abbr = m.group(1).strip(), m.group(2).strip()
        if base:
            parts.append(base)
        if abbr:
            parts.append(abbr)
        return parts
    return [t]


def normalize_keywords(raw):
    """Normalize keywords string: lowercase-hyphen, split parentheticals, dedup."""
    if not raw:
        return raw
    seen = set()
    result = []
    for t in re.split(r"[,;]", raw):
        t = t.strip()
        if not t:
            continue
        for p in _split_parentheses(t):
            tag = _normalize_tag(p)
            if tag and tag not in seen:
                result.append(tag)
                seen.add(tag)
    return ", ".join(result)


def _match_cat_for_term(term, search_order):
    """Return the first matching category for a single term."""
    for cat, kw in search_order:
        if kw in term:
            return cat
    return None


def categorize(title, extra_keywords=None, filename=None):
    """Count-based classification: most Index Terms hits wins, ties broken by title."""
    t = title.lower().replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')

    if _PATENT_RE.search(title):
        return 'Patent'
    if filename and _PATENT_RE.search(filename):
        return 'Patent'

    search_order = sorted(
        [(cat, kw) for cat, keywords in CATS.items() for kw in keywords],
        key=lambda x: len(x[1]),
        reverse=True,
    )

    # 统计各 cat 在 Index Terms 中的命中数
    cat_hits = {}
    if extra_keywords:
        ek = extra_keywords.lower().replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
        for term in re.split(r'[,;]\s*', ek):
            term = term.strip()
            if len(term) < 2:
                continue
            cat = _match_cat_for_term(term, search_order)
            if cat:
                cat_hits[cat] = cat_hits.get(cat, 0) + 1

    # 命中最多的 cat，持平用标题 tiebreak
    if cat_hits:
        max_hits = max(cat_hits.values())
        top_cats = [c for c, h in cat_hits.items() if h == max_hits]
        if len(top_cats) == 1:
            return top_cats[0]
        # 持平：在 top_cats 范围内用标题匹配 tiebreak
        for cat, kw in search_order:
            if cat in top_cats and kw in t:
                return cat

    # 无 Index Terms 或无命中：标题 fallback
    for cat, kw in search_order:
        if kw in t:
            return cat

    return 'Others'


# ============================================================
# Unified PDF extraction (ONE open per file, with cache)
# ============================================================
_pdf_info_cache = {}


def extract_pdf_info(pdf_path):
    """
    ONE-SHOT extraction: open the PDF once, extract all metadata.
    Returns dict: {doc_id, title, year, keywords, doi}
    Results are cached by file path.
    """
    cache_key = str(pdf_path)
    if cache_key in _pdf_info_cache:
        return _pdf_info_cache[cache_key]

    result = {'doc_id': None, 'title': '', 'year': '', 'keywords': '', 'doi': None}

    if not HAS_FITZ:
        _pdf_info_cache[cache_key] = result
        return result

    # Skip very large files to prevent memory exhaustion
    try:
        file_size_mb = os.path.getsize(str(pdf_path)) / (1024 * 1024)
        if file_size_mb > MAX_PDF_SIZE_MB:
            safe_print(f"    [SKIP] Too large ({file_size_mb:.0f}MB): {Path(pdf_path).name[:60]}")
            _pdf_info_cache[cache_key] = result
            return result
    except OSError:
        _pdf_info_cache[cache_key] = result
        return result

    doc = None
    try:
        doc = fitz.open(str(pdf_path))
        if doc is None:
            raise ValueError("fitz.open returned None")
        meta = doc.metadata or {}

        # ---- 1. doc_id from metadata ----
        for val in meta.values():
            if val and 'arnumber=' in str(val):
                m = re.search(r'arnumber=(\d{7,10})', str(val))
                if m:
                    result['doc_id'] = m.group(1)
                    break

        # ---- 2. title from metadata ----
        meta_title = meta.get('title', '').strip()
        if meta_title and len(meta_title) > 15 and not meta_title.startswith('Microsoft'):
            result['title'] = _html_unescape(meta_title)

        # ---- 3. year from metadata creation date (fallback only) ----
        creation = meta.get('creationDate', '')
        creation_year = ''
        ym = re.search(r'D:?((?:19|20)\d{2})', creation)
        if ym:
            creation_year = ym.group(1)

        # ---- 4. Extract text from first few pages ----
        num_pages = min(3, len(doc))
        page_texts = []
        for i in range(num_pages):
            try:
                page_texts.append(doc[i].get_text())
            except Exception:
                page_texts.append('')

        first_text = page_texts[0] if page_texts else ''
        two_page_text = '\n'.join(page_texts[:2])

        # ---- 4a. doc_id from text ----
        if not result['doc_id'] and first_text:
            for pattern in [
                r'arnumber[=:]?\s*(\d{7,10})',
                r'ieeexplore\.ieee\.org/document/(\d{7,10})',
                r'10\.\d{4}/[A-Z]+\.\d{4}\.(\d{7,10})',
            ]:
                m = re.search(pattern, first_text)
                if m:
                    result['doc_id'] = m.group(1)
                    break

        # ---- 4b. year from text (PRIORITY: publication date > creation date) ----
        # Try text-based extraction first — these give the actual publication year
        if first_text:
            for pattern in [
                # Highest priority: explicit publication date
                r'date of publication[;:,]?\s*\d{1,2}\s+\w+\s+(20[12]\d)',
                r'date of current version[;:,]?\s*\d{1,2}\s+\w+\s+(20[12]\d)',
                # IEEE copyright line
                r'(20[12]\d)\s*IEEE',
                # Journal volume header
                r'VOL\.?\s*\d+.*?(20[12]\d)',
                # General IEEE mention
                r'IEEE.*?(20[12]\d)',
                # Accepted/received dates (less reliable but still actual paper dates)
                r'(?:accepted|received).*?\d{1,2}\s+\w+\s+(20[12]\d)',
                # DOI-embedded year
                r'10\.\d{4,}/[\w.]+\.(20[12]\d)\.\d+',
            ]:
                m = re.search(pattern, first_text, re.IGNORECASE)
                if m:
                    yr_str = m.group(1) if m.lastindex else m.group(0)
                    ym2 = re.search(r'(20[12]\d)', yr_str)
                    if ym2:
                        result['year'] = ym2.group(1)
                        break

        # Fallback: use PDF metadata creation date only if text extraction failed
        if not result['year'] and creation_year:
            result['year'] = creation_year

        # ---- 4c. title from largest font on first page ----
        if not result['title'] and len(doc) > 0:
            try:
                page = doc[0]
                blocks = page.get_text("dict")["blocks"]
                best_size = 0
                for block in blocks:
                    if "lines" not in block:
                        continue
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span["size"] > best_size and len(span["text"].strip()) > 5:
                                best_size = span["size"]

                if best_size > 0:
                    title_parts = []
                    for block in blocks:
                        if "lines" not in block:
                            continue
                        for line in block["lines"]:
                            line_text = ''
                            is_title_font = False
                            for span in line["spans"]:
                                if abs(span["size"] - best_size) < 0.5:
                                    line_text += span["text"]
                                    is_title_font = True
                            if is_title_font and line_text.strip():
                                title_parts.append(line_text.strip())
                            elif title_parts:
                                break
                        if title_parts and not any(
                            abs(span["size"] - best_size) < 0.5
                            for line in block.get("lines", [])
                            for span in line["spans"]
                        ):
                            break

                    full_title = ' '.join(title_parts)
                    full_title = re.sub(r'\s+', ' ', full_title).strip()
                    full_title = full_title.replace('\ufb01', 'fi').replace('\ufb02', 'fl')
                    if len(full_title) > 15:
                        result['title'] = full_title
            except Exception:
                pass

        # ---- 4d. keywords ----
        if two_page_text:
            m = re.search(
                r'(?:Index\s*Terms|Keywords)\s*[\u2014:\-\u2013]\s*(.+?)(?:\n\s*\n|I\.\s|1\.\s|INTRODUCTION)',
                two_page_text, re.IGNORECASE | re.DOTALL
            )
            if m:
                kw = m.group(1).strip()
                kw = re.sub(r'(\w)-\s+([a-z])', r'\1\2', kw)
                kw = kw.replace('\ufb01', 'fi').replace('\ufb02', 'fl')
                kw = re.sub(r'\s+', ' ', kw).rstrip('.')
                result['keywords'] = normalize_keywords(kw)

        # ---- 4e. DOI ----
        for text in page_texts:
            m = re.search(r'(10\.\d{4,}/[^\s]+)', text)
            if m:
                result['doi'] = m.group(0)
                break

    except Exception as e:
        safe_print(f"    [ERROR] PDF parse failed: {Path(pdf_path).name[:50]}: {str(e)[:80]}")
    finally:
        if doc:
            try:
                doc.close()
            except Exception:
                pass
        doc = None

    _pdf_info_cache[cache_key] = result
    return result


def clear_pdf_cache():
    """Release cached PDF info to free memory."""
    global _pdf_info_cache
    _pdf_info_cache.clear()
    gc.collect()


# ---- Thin wrappers for backward compatibility ----
def extract_pdf_keywords(pdf_path):
    return extract_pdf_info(pdf_path).get('keywords', '')

def extract_pdf_doc_id(pdf_path):
    return extract_pdf_info(pdf_path).get('doc_id')

def extract_pdf_title(pdf_path):
    return extract_pdf_info(pdf_path).get('title', '')

def extract_pdf_year(pdf_path):
    return extract_pdf_info(pdf_path).get('year', '')

def extract_doi_from_pdf(pdf_path):
    return extract_pdf_info(pdf_path).get('doi')


# ============================================================
# Filename helpers
# ============================================================
def extract_doc_id(filename):
    """Extract docId from filename like 2026_ADC_..._11333284.pdf"""
    m = re.search(r'_(\d{7,10})\.pdf$', filename, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'10\.1109@[^\s_]+_(\d+)\.pdf$', filename, re.IGNORECASE)
    if m:
        return m.group(1)
    nums = re.findall(r'(\d{7,10})', filename)
    return nums[-1] if nums else None


def extract_year(filename):
    m = re.match(r'^(\d{4})_', filename)
    return m.group(1) if m else None


def title_from_filename(filename):
    """Reconstruct rough title from filename, stripping ALL repeated prefixes."""
    name = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
    name = re.sub(r'_(\d{7,10})$', '', name)
    name = re.sub(r'^\d{4}_', '', name)
    all_cats = list(CATS.keys()) + ['Others', 'Patent']
    all_cats.sort(key=lambda c: -len(c))
    # Strip ALL repeated category prefixes (not just one)
    changed = True
    while changed:
        changed = False
        for cat in all_cats:
            if name.startswith(cat + '_'):
                name = name[len(cat)+1:]
                changed = True
                break
        # Also strip year prefixes that may appear mid-name
        m = re.match(r'^\d{4}_', name)
        if m:
            name = name[5:]
            changed = True
    return name.replace('_', ' ')


def _html_unescape(s):
    """Unescape HTML entities and clean up."""
    import html as html_mod
    s = html_mod.unescape(s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return s

# Keep old name for any references
html_unescape = _html_unescape


# ============================================================
# Step 1: Collect all papers (meta + filesystem scan)
# ============================================================
def _load_meta_entries(filepath):
    """Load paper entries from a meta JSON file."""
    if not filepath.exists():
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def _add_meta_entry(papers, entry):
    """Add a single meta entry into papers dict (dedup by docId)."""
    did = entry.get('docId')
    title = entry.get('title', '')
    if did:
        papers[did] = {
            'docId': did, 'title': title,
            'year': entry.get('year', ''),
            'category': entry.get('category', 'Others'),
            'pdfUrl': entry.get('pdfUrl', ''),
            'savePath': entry.get('savePath', ''),
            'files': [],
            'pdf_keywords': entry.get('keywords', ''),
            'titleChecked': entry.get('titleChecked', False),
        }
    elif title and len(title) > 5:
        did = 'T_' + hashlib.md5(title.lower().encode()).hexdigest()[:10]
        papers[did] = {
            'docId': '', 'title': title,
            'year': entry.get('year', ''),
            'category': entry.get('category', 'Others'),
            'pdfUrl': entry.get('pdfUrl', ''),
            'savePath': entry.get('savePath', ''),
            'files': [],
            'pdf_keywords': entry.get('keywords', ''),
            'titleChecked': entry.get('titleChecked', False),
        }


def collect_papers():
    papers = {}

    # 1a. load from master paper_meta.json
    for entry in _load_meta_entries(META_FILE):
        _add_meta_entry(papers, entry)

    # 1b. merge paper_meta_new.json (Chrome extension new downloads)
    new_meta_file = BASE_DIR / "paper_meta_new.json"
    if new_meta_file.exists():
        new_count = 0
        for entry in _load_meta_entries(new_meta_file):
            did = entry.get('docId')
            if did and did not in papers:
                _add_meta_entry(papers, entry)
                new_count += 1
        if new_count > 0:
            safe_print(f"  Merged {new_count} new entries from paper_meta_new.json")

    # 1c. scan all PDF files (including subdirectories)
    scanned_files = set()
    all_pdfs = []  # collect first, then process in batches

    for input_dir in INPUT_DIRS:
        if not input_dir.exists():
            safe_print(f"  [WARNING] Directory not found: {input_dir}")
            continue

        for subdir in input_dir.iterdir():
            if subdir.is_dir() and subdir.name not in STD_CATEGORIES and subdir.name != '0_inbox':
                IMPORTED_FOLDERS.append(subdir)

        # Collect both .pdf and .PDF
        for pdf_path in input_dir.rglob('*.pdf'):
            if '_duplicates' in str(pdf_path):
                continue
            key = str(pdf_path)
            if key not in scanned_files:
                scanned_files.add(key)
                all_pdfs.append(pdf_path)
        for pdf_path in input_dir.rglob('*.PDF'):
            if '_duplicates' in str(pdf_path):
                continue
            key = str(pdf_path)
            if key not in scanned_files:
                scanned_files.add(key)
                all_pdfs.append(pdf_path)

    safe_print(f"  Scanning {len(all_pdfs)} PDF files...")

    for idx, pdf_path in enumerate(all_pdfs):
        # Progress reporting
        if idx > 0 and idx % PROGRESS_INTERVAL == 0:
            safe_print(f"    ... processed {idx}/{len(all_pdfs)} files")

        # Batch memory cleanup
        if idx > 0 and idx % BATCH_SIZE == 0:
            gc.collect()

        try:
            fname = pdf_path.name
            did = extract_doc_id(fname)

            if did:
                if did in papers:
                    papers[did]['files'].append(pdf_path)
                    current_title = papers[did].get('title', '')
                    if not current_title or len(current_title) < 20 or current_title.startswith('10.1109'):
                        info = extract_pdf_info(pdf_path)
                        if info['title'] and len(info['title']) > len(current_title):
                            papers[did]['title'] = info['title']
                    cur_year = papers[did].get('year', '')
                    # Re-extract year if missing or in the future (likely wrong creation date)
                    current_yr = time.localtime().tm_year
                    try:
                        year_int = int(cur_year) if cur_year else 0
                    except ValueError:
                        year_int = 0
                    if not cur_year or year_int > current_yr:
                        info = extract_pdf_info(pdf_path)
                        if info['year']:
                            try:
                                info_year_int = int(info['year'])
                                if info_year_int <= current_yr:
                                    papers[did]['year'] = info['year']
                            except ValueError:
                                pass
                    if not papers[did].get('pdf_keywords'):
                        info = extract_pdf_info(pdf_path)
                        if info['keywords']:
                            papers[did]['pdf_keywords'] = info['keywords']
                else:
                    fname_year = extract_year(fname) or ''
                    title = title_from_filename(fname)
                    info = extract_pdf_info(pdf_path)

                    if info['title'] and len(info['title']) > len(title):
                        title = info['title']
                    # PDF text-extracted year is MORE reliable than filename year
                    # (filename year often comes from PDF creation date, not publication)
                    year = info['year'] or fname_year

                    papers[did] = {
                        'docId': did,
                        'title': title,
                        'year': year,
                        'category': 'Others',
                        'pdfUrl': f'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={did}',
                        'savePath': '',
                        'files': [pdf_path],
                        'pdf_keywords': info['keywords'],
                    }
            else:
                # no docId in filename
                info = extract_pdf_info(pdf_path)
                did_from_pdf = info['doc_id']
                pdf_title = info['title']
                pdf_year = info['year']
                pdf_kw = info['keywords']

                fname_title = title_from_filename(fname)
                title = pdf_title if pdf_title and len(pdf_title) > 15 else fname_title

                if did_from_pdf and did_from_pdf in papers:
                    papers[did_from_pdf]['files'].append(pdf_path)
                    if pdf_title and len(pdf_title) > len(papers[did_from_pdf].get('title', '')):
                        papers[did_from_pdf]['title'] = pdf_title
                    if pdf_kw:
                        papers[did_from_pdf]['pdf_keywords'] = pdf_kw
                    continue
                elif did_from_pdf:
                    did = did_from_pdf
                else:
                    did = 'T_' + hashlib.md5(title.lower().encode()).hexdigest()[:10]

                if did not in papers:
                    is_special = False
                    reason = []

                    if not did_from_pdf and (not pdf_title or len(pdf_title) < 20):
                        is_special = True
                        reason.append("No IEEE docId and title extraction failed")
                    if not pdf_year:
                        is_special = True
                        reason.append("No year information")
                    if len(title) < 15:
                        is_special = True
                        reason.append("Title too short")
                    lower_title = title.lower()
                    if any(kw in lower_title for kw in ['thesis', 'dissertation', 'technical report', 'university', 'master', 'phd']):
                        is_special = True
                        reason.append("Possible thesis/technical report")

                    if is_special and not did_from_pdf:
                        MANUAL_REVIEW.append({
                            'file': str(pdf_path),
                            'title': title,
                            'reason': '; '.join(reason),
                            'suggestion': 'Please manually rename: YYYY_Category_Title_docId.pdf'
                        })

                    papers[did] = {
                        'docId': did_from_pdf or '',
                        'title': title,
                        'year': pdf_year or '',
                        'category': 'Others',
                        'pdfUrl': f'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={did_from_pdf}' if did_from_pdf else '',
                        'savePath': '',
                        'files': [pdf_path],
                        'pdf_keywords': pdf_kw,
                        'needs_review': is_special and not did_from_pdf
                    }
                else:
                    papers[did]['files'].append(pdf_path)
        except Exception as e:
            safe_print(f"    [ERROR] Skipped {pdf_path.name[:50]}: {str(e)[:60]}")

    # Release PDF cache - no longer needed after collection
    clear_pdf_cache()

    # try to locate files for meta entries without files
    for did, p in papers.items():
        if not p['files'] and p['savePath']:
            sp = BASE_DIR.parent / p['savePath']
            if not sp.exists():
                sp = BASE_DIR / Path(p['savePath']).name
            if sp.exists():
                p['files'].append(sp)

    # fill missing titles from filenames
    for did, p in papers.items():
        if not p['title'] and p['files']:
            best = max(p['files'], key=lambda f: len(f.stem))
            t = title_from_filename(best.name)
            if t and t != did:
                p['title'] = t
            y = extract_year(best.name)
            if y:
                p['year'] = y

    return papers


# ============================================================
# Step 1b: Fetch missing/truncated titles from IEEE Xplore
# ============================================================
FETCH_WORKERS = 2          # concurrent fetchers (reduced to avoid IP ban)
FETCH_DELAY = 1.0          # seconds between requests per worker
FETCH_MAX_RETRIES = 3      # max retries on failure


def fetch_title_from_ieee(doc_id):
    """Fetch paper title from IEEE Xplore metadata API (fast, small payload)."""
    # Try the lightweight metadata API first
    api_url = f"https://ieeexplore.ieee.org/rest/document/{doc_id}/metadata"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': f'https://ieeexplore.ieee.org/document/{doc_id}',
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
        title = data.get('title', '').strip()
        if title and len(title) > 10:
            return _html_unescape(re.sub(r'<[^>]+>', '', title))
    except Exception:
        pass

    # Fallback: fetch HTML page
    url = f"https://ieeexplore.ieee.org/document/{doc_id}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            page = resp.read().decode('utf-8', errors='ignore')
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page)
        if m:
            return _html_unescape(m.group(1))
        m = re.search(r'<title>([^<]+)</title>', page)
        if m:
            t = m.group(1).strip()
            t = re.sub(r'\s*[-|].*IEEE.*$', '', t)
            return _html_unescape(t)
    except Exception as e:
        safe_print(f"    Warning: failed to fetch {doc_id}: {str(e)[:60]}")
    return None


def fetch_title_with_retry(doc_id, max_retries=None):
    """Fetch title with exponential backoff retry."""
    if max_retries is None:
        max_retries = FETCH_MAX_RETRIES
    for attempt in range(max_retries):
        try:
            # Exponential backoff: 1s, 2s, 4s
            if attempt > 0:
                backoff = FETCH_DELAY * (2 ** attempt)
                time.sleep(backoff)
            result = fetch_title_from_ieee(doc_id)
            if result:
                return result
        except Exception as e:
            if attempt == max_retries - 1:
                safe_print(f"    Error: fetch failed after {max_retries} retries for {doc_id}")
    return None


def is_title_truncated(title):
    """Check if a title looks truncated."""
    if not title or len(title) < 15:
        return True
    # Very short titles are suspicious
    if len(title) < 20:
        return True
    # Check for obvious truncation patterns
    truncation_patterns = [
        # Ends with preposition/conjunction (likely truncated mid-phrase)
        r'\b(With|For|In|On|At|By|Of|And|Or|Using|Based|From|To|Into|Through|Via|Via)\s*$',
        # Ends with comma or hyphen (continuation expected)
        r'[,\-–—]\s*$',
        # Ends mid-word (consonant not typical for English word endings)
        r'(?:[bcdfghjkmnpqrstvwxz]{2}|[bcfghjkmnpqrstvwxz]{3})\s*$',
    ]
    for pattern in truncation_patterns:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    # Ends with incomplete word pattern (e.g., "A 0.5-V" at end)
    if re.search(r'\b(A|An|The|A\s+\d+)\s*$', title, re.IGNORECASE):
        return True
    return False


def extract_title_from_pdf_largest_font(pdf_path):
    """Extract title from PDF by finding largest font text on first page."""
    if not HAS_FITZ:
        return ''
    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) == 0:
            return ''
        page = doc[0]
        blocks = page.get_text("dict")["blocks"]
        best_size = 0
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["size"] > best_size and len(span["text"].strip()) > 5:
                        best_size = span["size"]
        if best_size <= 0:
            return ''
        title_parts = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ''
                is_title_font = False
                for span in line["spans"]:
                    if abs(span["size"] - best_size) < 0.5:
                        line_text += span["text"]
                        is_title_font = True
                if is_title_font and line_text.strip():
                    title_parts.append(line_text.strip())
                elif title_parts:
                    break
            if title_parts and not any(
                abs(span["size"] - best_size) < 0.5
                for line in block.get("lines", [])
                for span in line["spans"]
            ):
                break
        full_title = ' '.join(title_parts)
        full_title = re.sub(r'\s+', ' ', full_title).strip()
        full_title = full_title.replace('\ufb01', 'fi').replace('\ufb02', 'fl')
        doc.close()
        return full_title if len(full_title) > 15 else ''
    except Exception:
        return ''


def complete_titles(papers):
    """Fix truncated titles: first try PDF largest-font extraction, then IEEE website.
    Papers already checked are skipped (titleChecked flag in meta)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    to_fix = []
    for did, p in papers.items():
        # Skip papers already checked in previous runs
        if p.get('titleChecked'):
            continue
        real_did = p.get('docId', '')
        if not real_did or real_did.startswith('T_'):
            continue
        if is_title_truncated(p.get('title', '')):
            files = p.get('files', [])
            to_fix.append((did, files[0] if files else None))

    if not to_fix:
        return 0

    safe_print(f"  Found {len(to_fix)} papers with truncated titles...")

    # Phase 1: Try local PDF extraction (fast, no network)
    pdf_fixed = 0
    still_need_web = []
    for did, file_path in to_fix:
        if file_path and file_path.exists():
            new_title = extract_title_from_pdf_largest_font(file_path)
            if new_title and not is_title_truncated(new_title):
                old_title = papers[did].get('title', '')
                if len(new_title) > len(old_title):
                    papers[did]['title'] = new_title
                    pdf_fixed += 1
                papers[did]['titleChecked'] = True
                continue
        still_need_web.append(did)

    if pdf_fixed:
        safe_print(f"    Fixed {pdf_fixed} titles from PDF directly")

    if not still_need_web:
        return pdf_fixed

    # Phase 2: Fallback to IEEE website for remaining
    safe_print(f"    Fetching {len(still_need_web)} titles from IEEE website ({FETCH_WORKERS} workers)...")

    def _fetch_one(did):
        time.sleep(FETCH_DELAY)
        return did, fetch_title_with_retry(did)

    web_fixed = 0
    done = 0
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, did): did for did in still_need_web}
        for future in as_completed(futures):
            done += 1
            did, new_title = future.result()
            old_title = papers[did].get('title', '')
            if new_title and len(new_title) > len(old_title):
                papers[did]['title'] = new_title
                web_fixed += 1
            # Mark as checked regardless of success — don't retry 404s
            papers[did]['titleChecked'] = True
            if done % 10 == 0 or done == len(still_need_web):
                safe_print(f"      ... {done}/{len(still_need_web)} web fetches done")

    return pdf_fixed + web_fixed


# ============================================================
# Step 2: Re-classify and deduplicate
# ============================================================
def reclassify_and_dedup(papers, dry_run=False, verbose=False):
    stats = {'reclassified': 0, 'duplicates_removed': 0, 'keywords_used': 0, 'total': len(papers)}

    for did, p in papers.items():
        old_cat = p['category']

        # Use already-extracted keywords (no more PDF re-opening!)
        pdf_kw = p.get('pdf_keywords', '')
        if pdf_kw:
            stats['keywords_used'] += 1

        # Pass filename so patent patterns in filename can be detected
        fname = p['files'][0].name if p['files'] else p.get('savePath', '')
        new_cat = categorize(p['title'], extra_keywords=pdf_kw, filename=fname)
        if new_cat != 'Others':
            p['new_category'] = new_cat
            if new_cat != old_cat:
                stats['reclassified'] += 1
        else:
            p['new_category'] = old_cat

        # deduplicate
        if len(p['files']) > 1:
            def file_quality_score(f):
                """Score file quality: size > naming > mtime"""
                score = 0
                try:
                    score += f.stat().st_size  # Larger files are usually more complete
                except OSError:
                    pass
                # Bonus for standard naming: YYYY_Category_Title_docId.pdf
                if re.match(r'^\d{4}_[A-Za-z]+_.+_\d{7,}\.pdf$', f.name):
                    score += 10000000
                return score
            try:
                p['files'].sort(key=file_quality_score, reverse=True)
            except OSError:
                pass
            keeper = p['files'][0]
            for dup in p['files'][1:]:
                if dry_run:
                    if verbose:
                        safe_print(f"  [DRY-RUN] Would dedup: {dup.name[:60]}")
                    stats['duplicates_removed'] += 1
                else:
                    try:
                        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                        dest = BACKUP_DIR / dup.name
                        if dest.exists():
                            dest = BACKUP_DIR / f"{dup.stem}_dup{dest.suffix}"
                        if verbose:
                            safe_print(f"  [DEDUP] {dup.name[:60]}")
                        shutil.move(str(dup), str(dest))
                        stats['duplicates_removed'] += 1
                    except Exception as e:
                        safe_print(f"  [DEDUP ERROR] {dup.name[:40]}: {str(e)[:40]}")
            p['files'] = [keeper]

    return stats


# ============================================================
# Step 3: Move files to correct category folders
# ============================================================
def reorganize_files(papers, dry_run=False, verbose=False):
    moved = 0
    for did, p in papers.items():
        cat = p['new_category']
        if not p['files']:
            continue

        src = p['files'][0]
        if not src.exists():
            continue

        target_dir = BASE_DIR / cat
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        title = p.get('title', '')
        year = p.get('year', '')
        real_docid = p.get('docId', '')

        if title and len(title) > 10:
            title_clean = re.sub(r'[<>:"/\\|?*]', '', title)
            title_clean = re.sub(r'\s+', ' ', title_clean).strip()
            # Strip any remaining category/year prefixes from title
            all_cats = list(CATS.keys()) + ['Others', 'Patent']
            all_cats.sort(key=lambda c: -len(c))
            _changed = True
            while _changed:
                _changed = False
                for _cat in all_cats:
                    if title_clean.startswith(_cat + ' '):
                        title_clean = title_clean[len(_cat)+1:]
                        _changed = True
                        break
                _m = re.match(r'^\d{4}\s+', title_clean)
                if _m:
                    title_clean = title_clean[_m.end():]
                    _changed = True
            title_clean = title_clean.strip()
            if len(title_clean) > 150:
                title_clean = title_clean[:150].strip()
            title_clean = title_clean.replace(' ', '_')
            parts = []
            if year:
                parts.append(year)
            parts.append(cat)
            parts.append(title_clean)
            if real_docid:
                parts.append(real_docid)
            new_name = '_'.join(parts) + '.pdf'
            new_name = re.sub(r'_+', '_', new_name)
        else:
            new_name = src.name

        dest = target_dir / new_name

        if src == dest:
            p['final_path'] = dest
            p['savePath'] = f"ieee_papers/{cat}/{new_name}"
            continue

        if src.parent != target_dir or src.name != new_name:
            if dry_run:
                if verbose:
                    safe_print(f"  [DRY-RUN] Would move: {src.name[:60]} -> {cat}/{new_name[:60]}")
                moved += 1
            else:
                try:
                    if dest.exists() and src != dest:
                        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(BACKUP_DIR / src.name))
                    else:
                        shutil.move(str(src), str(dest))
                        moved += 1
                except Exception as e:
                    safe_print(f"  [MOVE ERROR] {src.name[:40]}: {str(e)[:40]}")

        p['final_path'] = dest
        p['savePath'] = f"ieee_papers/{cat}/{new_name}"

    return moved


# ============================================================
# Step 4: Clean up empty folders
# ============================================================
def cleanup_empty_dirs():
    removed = []
    changed = True
    while changed:
        changed = False
        for root, dirs, files in os.walk(BASE_DIR, topdown=False):
            for d in dirs:
                dir_path = Path(root) / d
                if dir_path.name in ('_duplicates', '0_inbox'):
                    continue
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        removed.append(str(dir_path.relative_to(BASE_DIR)))
                        changed = True
                except Exception:
                    pass

    if removed:
        print(f"  [CLEAN] Removed {len(removed)} empty folders")
        for r in removed[:5]:
            print(f"    - {r}")
        if len(removed) > 5:
            print(f"    ... and {len(removed) - 5} more")
    return removed


# ============================================================
# Step 5: Update paper_meta.json
# ============================================================
def update_meta(papers):
    meta = []
    for did, p in sorted(papers.items(), key=lambda x: (x[1]['new_category'], x[1]['title'])):
        entry = {
            'title': p['title'],
            'docId': p.get('docId', '') or (did if not did.startswith('T_') else ''),
            'category': p['new_category'],
            'year': p['year'],
            'pdfUrl': p['pdfUrl'],
            'savePath': p.get('savePath', ''),
        }
        if p.get('pdf_keywords'):
            entry['keywords'] = p['pdf_keywords']
        if p.get('titleChecked'):
            entry['titleChecked'] = True
        meta.append(entry)
    with open(META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return len(meta)


# ============================================================
# Step 6: Generate HTML search/filter page
# ============================================================
def _resolve_pdf_path(p, doc_id, cat, base_dirs):
    """Resolve PDF path: check final_path, savePath, files list, then search by docId."""
    # 1. final_path from reorganize
    final = p.get('final_path')
    if final and final.exists():
        for bd in base_dirs:
            try: return str(final.relative_to(bd)).replace('\\', '/')
            except ValueError: pass
    # 2. savePath from meta
    sp = p.get('savePath', '')
    if sp:
        sp = sp.replace('ieee_papers/', '', 1)
        for bd in base_dirs:
            if (bd / sp).exists():
                return sp
    # 3. files list from scan
    for f in p.get('files', []):
        if f.exists():
            for bd in base_dirs:
                try: return str(f.relative_to(bd)).replace('\\', '/')
                except ValueError: pass
    # 4. Search category folder by docId
    if doc_id and not doc_id.startswith('T_'):
        for bd in base_dirs:
            cat_dir = bd / cat
            if cat_dir.is_dir():
                for f in cat_dir.iterdir():
                    if f.is_file() and doc_id in f.name:
                        try: return str(f.relative_to(bd)).replace('\\', '/')
                        except ValueError: pass
    return ''


def generate_html(papers):
    base_dirs = [BASE_DIR]
    if _SCRIPT_DIR.parent != BASE_DIR:
        base_dirs.append(_SCRIPT_DIR.parent)

    records = []
    for did, p in papers.items():
        cat = p.get('new_category') or p.get('category', 'Others')
        year = p['year'] or ''
        title = p['title']
        doc_id = p.get('docId', '') or (did if not did.startswith('T_') else '')
        ieee_url = f"{IEEE_BASE_URL}{doc_id}" if doc_id else ''
        pdf_kw = p.get('pdf_keywords', '')
        pdf_rel = _resolve_pdf_path(p, doc_id, cat, base_dirs)
        records.append({
            'id': doc_id or did,
            't': title,
            'c': cat,
            'y': year,
            'u': ieee_url,
            'p': pdf_rel,
            'k': pdf_kw,
        })

    records.sort(key=lambda r: (r['c'], r['t']))

    cats_set = sorted(set(r['c'] for r in records))
    years_set = sorted(set(r['y'] for r in records if r['y']), reverse=True)

    data_json = json.dumps(records, ensure_ascii=False)

    # Build HTML template (using % formatting to avoid f-string brace issues)
    html_tpl = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IEEE Paper Library</title>
<style>
:root {
  --bg: #f0f2f5; --card-bg: #fff; --text: #333; --text2: #666;
  --border: #e0e0e0; --shadow: rgba(0,0,0,0.06);
  --header-bg: linear-gradient(135deg,#667eea,#764ba2);
  --input-bg: #fff; --input-border: #d0d0d0;
  --chip-hover: rgba(0,0,0,0.04); --mark-bg: #fef08a;
  --kbd-bg: #e8e8e8; --kbd-text: #555;
  --cat-hover-bg: #f8f9ff;
}
.dark {
  --bg: #1a1b23; --card-bg: #252630; --text: #ddd; --text2: #999;
  --border: #333; --shadow: rgba(0,0,0,0.3);
  --header-bg: linear-gradient(135deg,#3d3a6e,#4a2e6e);
  --input-bg: #2a2b35; --input-border: #444;
  --chip-hover: rgba(255,255,255,0.06); --mark-bg: #a09000;
  --kbd-bg: #333; --kbd-text: #ccc;
  --cat-hover-bg: #2a2b40;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:var(--text); transition:background 0.3s,color 0.3s; }

.header {
  background:var(--header-bg); color:#fff; padding:14px 24px;
  position:sticky; top:0; z-index:100; display:flex;
  align-items:center; gap:16px; box-shadow:0 2px 12px rgba(0,0,0,0.15);
}
.header h1 { font-size:18px; font-weight:700; }
.header .subtitle { font-size:12px; opacity:0.8; margin-left:4px; }
.header .hdr-right { margin-left:auto; display:flex; align-items:center; gap:10px; }
.header .hdr-btn {
  background:rgba(255,255,255,0.15); color:#fff; border:none;
  border-radius:6px; padding:5px 10px; cursor:pointer; font-size:13px;
  transition:background 0.2s;
}
.header .hdr-btn:hover { background:rgba(255,255,255,0.25); }

.toolbar {
  background:var(--card-bg); padding:10px 20px; border-bottom:1px solid var(--border);
  display:flex; gap:10px; flex-wrap:wrap; align-items:center;
  position:sticky; top:52px; z-index:99; box-shadow:0 1px 4px var(--shadow);
  transition:background 0.3s;
}
.toolbar input[type=text] {
  flex:1; min-width:160px; padding:7px 12px; border:1px solid var(--input-border);
  border-radius:6px; font-size:13px; outline:none; background:var(--input-bg); color:var(--text);
  transition:border 0.2s,background 0.3s;
}
.toolbar input[type=text]:focus { border-color:#667eea; }
.toolbar select {
  padding:7px 10px; border:1px solid var(--input-border); border-radius:6px;
  font-size:13px; background:var(--input-bg); color:var(--text); cursor:pointer; outline:none;
}
.toolbar .count { font-size:12px; color:var(--text2); white-space:nowrap; }

.cat-bar {
  background:var(--card-bg); padding:8px 20px; border-bottom:1px solid var(--border);
  display:flex; gap:5px; flex-wrap:wrap; align-items:center;
  position:sticky; top:94px; z-index:98;
  transition:background 0.3s;
}
.cat-bar .cat-chip {
  display:inline-flex; align-items:center; gap:3px;
  padding:3px 10px; border-radius:14px; font-size:11px; font-weight:600;
  cursor:pointer; border:1px solid transparent; user-select:none;
  transition:all 0.15s;
}
.cat-bar .cat-chip:hover { filter:brightness(0.9); }
.cat-bar .cat-chip.off { opacity:0.35; background:#ccc !important; color:#666 !important; border-color:#ccc !important; }
.cat-bar .cat-chip .num { font-size:10px; opacity:0.9; }
.cat-bar .cat-actions { display:flex; gap:4px; margin-left:4px; }
.cat-bar .cat-act-btn {
  font-size:10px; padding:3px 8px; border-radius:10px; border:1px solid var(--border);
  background:var(--card-bg); color:var(--text2); cursor:pointer; transition:all 0.15s;
}
.cat-bar .cat-act-btn:hover { background:var(--chip-hover); color:var(--text); }

.paper-list { max-width:1200px; margin:0 auto; padding:12px 20px 80px; }

.paper-card {
  background:var(--card-bg); border-radius:6px; padding:8px 14px; margin-bottom:3px;
  display:flex; align-items:center; gap:10px;
  transition:all 0.15s; border-left:3px solid transparent;
  cursor:default;
}
.paper-card:hover { background:var(--cat-hover-bg); }
.paper-card.focus { background:var(--cat-hover-bg); box-shadow:inset 0 0 0 1px #667eea; }
.paper-card .info { flex:1; min-width:0; }
.paper-card .title {
  font-size:13px; font-weight:600; line-height:1.4; color:var(--text);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  margin-bottom:2px;
}
.paper-card .title:hover { white-space:normal; overflow:visible; }
.paper-card .meta {
  display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:11px; color:var(--text2);
}
.paper-card .tag { display:inline-block; padding:1px 7px; border-radius:10px; font-size:10px; font-weight:600; color:#fff; }
.paper-card .year { padding:1px 6px; border-radius:10px; font-size:10px; font-weight:600; background:var(--kbd-bg); color:var(--kbd-text); }
.paper-card .docid { font-size:10px; opacity:0.6; }
.paper-card .kw {
  font-size:10px; color:var(--text2); opacity:0.8; line-height:1.3;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:600px;
}

.paper-card .links { display:flex; gap:4px; flex-shrink:0; }
.paper-card .links a {
  display:inline-flex; align-items:center; justify-content:center;
  width:30px; height:30px; border-radius:6px; text-decoration:none;
  transition:all 0.15s;
}
.link-ieee { background:rgba(102,126,234,0.1); color:#667eea; }
.link-ieee:hover { background:#667eea; color:#fff; }
.link-pdf { background:rgba(56,161,105,0.1); color:#38a169; }
.link-pdf:hover { background:#38a169; color:#fff; }

.cat-hdr {
  font-size:12px; font-weight:700; color:#667eea; margin:16px 0 4px;
  padding-bottom:3px; border-bottom:1px solid var(--border);
  display:flex; align-items:center; gap:6px;
}
.cat-hdr .cat-n { font-size:10px; font-weight:600; background:#667eea; color:#fff; padding:1px 6px; border-radius:8px; }

.no-results { text-align:center; padding:60px 20px; color:var(--text2); font-size:14px; }

mark { background:var(--mark-bg); padding:0 1px; border-radius:2px; color:inherit; }

.help-overlay {
  display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:999;
  justify-content:center; align-items:center;
}
.help-overlay.show { display:flex; }
.help-box { background:var(--card-bg); border-radius:10px; padding:24px 28px; max-width:380px; width:90%%; }
.help-box h3 { margin-bottom:12px; font-size:15px; color:var(--text); }
.help-box kbd {
  display:inline-block; padding:1px 6px; border-radius:4px; font-size:11px;
  background:var(--kbd-bg); color:var(--kbd-text); font-family:monospace; margin-right:2px;
}
.help-box .row { display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:var(--text2); }
</style>
</head>
<body>

<div class="header">
  <h1>IEEE Paper Library</h1>
  <span class="subtitle" id="hdrInfo"></span>
  <div class="hdr-right">
    <button class="hdr-btn" id="helpBtn" title="Shortcuts">?</button>
    <button class="hdr-btn" id="themeBtn" title="Toggle dark mode">🌙</button>
  </div>
</div>

<div class="toolbar">
  <input type="text" id="search" placeholder="Search: emi (whole word) | &quot;emi&quot; (substring) | sar adc (both)..." autocomplete="off">
  <select id="filterYear"><option value="">All Years</option></select>
  <select id="sortSel">
    <option value="cat">Category</option>
    <option value="year_desc">Year (New→Old)</option>
    <option value="year_asc">Year (Old→New)</option>
    <option value="title">Title A→Z</option>
  </select>
  <span class="count" id="resultCount"></span>
</div>

<div class="cat-bar" id="catBar"></div>

<div class="paper-list" id="paperList"></div>

<div class="help-overlay" id="helpOverlay">
  <div class="help-box">
    <h3>Keyboard Shortcuts</h3>
    <div class="row"><span><kbd>j</kbd> / <kbd>k</kbd> or <kbd>↓</kbd> / <kbd>↑</kbd></span><span>Navigate papers</span></div>
    <div class="row"><span><kbd>Enter</kbd></span><span>Open PDF / IEEE link</span></div>
    <div class="row"><span><kbd>/</kbd></span><span>Focus search</span></div>
    <div class="row"><span><kbd>Esc</kbd></span><span>Clear filters</span></div>
    <div class="row"><span><kbd>?</kbd></span><span>Toggle this help</span></div>
  </div>
</div>

<script>
var DATA = %s;

var CAT_COLORS = {
  'ADC':'#4299e1','DAC':'#48bb78','Amplifier':'#ed8936','AFE':'#e53e3e',
  'PLL':'#9f7aea','Clocking':'#d69e2e','Power':'#dd6b20','RF':'#38b2ac',
  'Radar':'#e53e3e','mmWave_THz':'#667eea','Wireline':'#319795',
  'SRAM':'#805ad5','Memory':'#d53f8c','CIM':'#00b5d8','Image_Sensor':'#f56565',
  'Bio_Sensor':'#68d391','LiDAR_ToF':'#fc8181','Env_Sensor':'#b794f4',
  'AI_Accelerator':'#f6ad55','DSP':'#63b3ed','Quantum':'#b794f4',
  'Security':'#fc8181','Comparator':'#90cdf4','Reference':'#fbb6ce',
  'Filter':'#9ae6b4','Packaging':'#fbd38d','Process_Technology':'#e9d8fd',
  'Patent':'#a0aec0','Others':'#cbd5e0'
};
function getColor(cat) { return CAT_COLORS[cat] || '#a0aec0'; }

var catSet = %s;
var yearSet = %s;
var selYear = document.getElementById('filterYear');
yearSet.forEach(function(y) { var o = document.createElement('option'); o.value = y; o.textContent = y; selYear.appendChild(o); });

var catCounts = {};
DATA.forEach(function(r) { catCounts[r.c] = (catCounts[r.c]||0) + 1; });
// Active categories (all on by default)
var activeCats = {};
catSet.forEach(function(c) { activeCats[c] = true; });

// Build category chips
var catBar = document.getElementById('catBar');
var catChips = {};
catSet.forEach(function(c) {
  if (!catCounts[c]) return;
  var chip = document.createElement('span');
  chip.className = 'cat-chip';
  chip.style.background = getColor(c) + '22';
  chip.style.color = getColor(c);
  chip.style.borderColor = getColor(c) + '44';
  chip.innerHTML = c + ' <span class="num">' + catCounts[c] + '</span>';
  chip.setAttribute('data-cat', c);
  chip.onclick = function() {
    activeCats[c] = !activeCats[c];
    this.classList.toggle('off', !activeCats[c]);
    render();
  };
  catBar.appendChild(chip);
  catChips[c] = chip;
});
// All/None buttons
var actDiv = document.createElement('span'); actDiv.className = 'cat-actions';
var allBtn = document.createElement('button'); allBtn.className = 'cat-act-btn'; allBtn.textContent = 'All';
allBtn.onclick = function() { catSet.forEach(function(c){ activeCats[c]=true; if(catChips[c]) catChips[c].classList.remove('off'); }); render(); };
var noneBtn = document.createElement('button'); noneBtn.className = 'cat-act-btn'; noneBtn.textContent = 'None';
noneBtn.onclick = function() { catSet.forEach(function(c){ activeCats[c]=false; if(catChips[c]) catChips[c].classList.add('off'); }); render(); };
actDiv.appendChild(allBtn); actDiv.appendChild(noneBtn); catBar.appendChild(actDiv);

var sortSel = document.getElementById('sortSel');
sortSel.addEventListener('change', render);

document.getElementById('hdrInfo').textContent = DATA.length + ' papers | ' + catSet.length + ' categories | ' + yearSet.join(', ');

var searchBox = document.getElementById('search');
var listEl = document.getElementById('paperList');
var countEl = document.getElementById('resultCount');
var focusIdx = -1;
var filteredCards = [];

// Dark mode
var themeBtn = document.getElementById('themeBtn');
var isDark = localStorage.getItem('ieee-dark') === '1';
function applyTheme() {
  document.body.classList.toggle('dark', isDark);
  themeBtn.textContent = isDark ? '☀' : '🌙';
}
applyTheme();
themeBtn.onclick = function() { isDark = !isDark; localStorage.setItem('ieee-dark', isDark?'1':'0'); applyTheme(); };

// Help overlay
var helpOverlay = document.getElementById('helpOverlay');
document.getElementById('helpBtn').onclick = function() { helpOverlay.classList.toggle('show'); };
helpOverlay.onclick = function(e) { if (e.target === helpOverlay) helpOverlay.classList.remove('show'); };

function parseQuery(raw) {
  var terms = [];
  var re = /"([^"]+)"/g, m, rest = raw;
  while ((m = re.exec(raw)) !== null) { terms.push({exact:true, val:m[1].toLowerCase()}); rest = rest.replace(m[0],' '); }
  rest.toLowerCase().split(/\\s+/).forEach(function(w) { if (w) terms.push({exact:false, val:w}); });
  return terms;
}

function matchTerms(terms, text) {
  for (var i = 0; i < terms.length; i++) {
    if (terms[i].exact) { if (text.indexOf(terms[i].val) === -1) return false; }
    else { var e = terms[i].val.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&'); if (!new RegExp('\\\\b'+e+'\\\\b','i').test(text)) return false; }
  }
  return true;
}

function render() {
  var q = searchBox.value.trim();
  var terms = parseQuery(q);
  var fy = selYear.value;
  var mode = sortSel.value;

  var filtered = DATA.filter(function(r) {
    if (!activeCats[r.c]) return false;
    if (fy && r.y !== fy) return false;
    if (terms.length) { var hay = (r.t + ' ' + (r.k||'')).toLowerCase(); if (!matchTerms(terms, hay)) return false; }
    return true;
  });

  if (mode === 'title') filtered.sort(function(a,b){ return a.t.localeCompare(b.t); });
  else if (mode === 'year_desc') filtered.sort(function(a,b){ return (b.y||'').localeCompare(a.y||'')||a.t.localeCompare(b.t); });
  else if (mode === 'year_asc') filtered.sort(function(a,b){ return (a.y||'').localeCompare(b.y||'')||a.t.localeCompare(b.t); });
  else filtered.sort(function(a,b){ return a.c.localeCompare(b.c)||a.t.localeCompare(b.t); });

  countEl.textContent = filtered.length + ' / ' + DATA.length;

  focusIdx = -1;
  var html = '';
  var lastGrp = '';
  filtered.forEach(function(r,i) {
    var grp = mode === 'cat' ? r.c : (mode === 'year_desc'||mode === 'year_asc') ? (r.y||'Unknown') : '';
    if (grp && grp !== lastGrp) {
      lastGrp = grp;
      var cc = 0; for (var j=i; j<filtered.length && ((mode==='cat'?filtered[j].c:filtered[j].y||'Unknown')===grp); j++) cc++;
      html += '<div class="cat-hdr"><span>' + esc(grp) + '</span><span class="cat-n">' + cc + '</span></div>';
    }
    var color = getColor(r.c);
    var idxAttr = ' data-idx="' + i + '"';
    html += '<div class="paper-card"' + idxAttr + ' style="border-left-color:' + color + '">';
    html += '<div class="info">';
    html += '<div class="title" title="' + esc(r.t) + '">' + highlight(esc(r.t), terms) + '</div>';
    html += '<div class="meta">';
    html += '<span class="tag" style="background:' + color + '">' + esc(r.c) + '</span>';
    if (r.y) html += '<span class="year">' + esc(r.y) + '</span>';
    if (r.id && r.id.indexOf('T_') !== 0) html += '<span class="docid">' + esc(r.id) + '</span>';
    html += '</div>';
    if (r.k) html += '<div class="kw">' + highlight(esc(r.k.length > 100 ? r.k.slice(0,100)+'...' : r.k), terms) + '</div>';
    html += '</div>';
    html += '<div class="links">';
    if (r.p) html += '<a class="link-pdf" href="' + esc(r.p) + '" target="_blank" title="Open PDF"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></a>';
    if (r.u) html += '<a class="link-ieee" href="' + esc(r.u) + '" target="_blank" rel="noopener" title="Open IEEE"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>';
    html += '</div></div>';
  });

  if (!filtered.length) html = '<div class="no-results">No papers match. Try adjusting filters or search terms.</div>';
  listEl.innerHTML = html;
  filteredCards = listEl.querySelectorAll('.paper-card');
}

function esc(s) { var d = document.createElement('div'); d.appendChild(document.createTextNode(s)); return d.innerHTML; }

function highlight(text, terms) {
  if (!terms.length) return text;
  var words = terms.map(function(t){ return t.val.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&'); });
  return text.replace(new RegExp('(' + words.join('|') + ')','gi'), '<mark>$1</mark>');
}

function focusCard(idx) {
  filteredCards.forEach(function(c){ c.classList.remove('focus'); });
  if (idx >= 0 && idx < filteredCards.length) {
    filteredCards[idx].classList.add('focus');
    filteredCards[idx].scrollIntoView({block:'nearest',behavior:'smooth'});
  }
}

function openCurrent() {
  if (focusIdx < 0 || focusIdx >= filteredCards.length) return;
  var card = filteredCards[focusIdx];
  var pdf = card.querySelector('.link-pdf');
  var ieee = card.querySelector('.link-ieee');
  if (pdf) window.open(pdf.href, '_blank');
  else if (ieee) window.open(ieee.href, '_blank');
}

searchBox.addEventListener('input', function(){ focusIdx = -1; render(); });
selYear.addEventListener('change', function(){ focusIdx = -1; render(); });

document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' && e.key !== 'Escape' && e.key !== '?') return;
  if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); focusIdx = Math.min(focusIdx+1, filteredCards.length-1); focusCard(focusIdx); }
  else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); focusIdx = Math.max(focusIdx-1, 0); focusCard(focusIdx); }
  else if (e.key === 'Enter') { e.preventDefault(); openCurrent(); }
  else if (e.key === '/') { e.preventDefault(); searchBox.focus(); searchBox.select(); }
  else if (e.key === 'Escape') { e.preventDefault(); searchBox.value = ''; selYear.value = ''; catSet.forEach(function(c){ activeCats[c]=true; if(catChips[c]) catChips[c].classList.remove('off'); }); focusIdx = -1; render(); }
  else if (e.key === '?') { e.preventDefault(); helpOverlay.classList.toggle('show'); }
});

render();
</script>
</body>
</html>"""

    html_content = html_tpl % (data_json, json.dumps(cats_set), json.dumps(years_set))

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)


# ============================================================
# Main
# ============================================================
def parse_args():
    """Parse command line arguments."""
    import argparse
    parser = argparse.ArgumentParser(
        description='IEEE Paper Manager - Organize and classify IEEE papers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python paper_manager.py                    # Full run: scan + classify + index
  python paper_manager.py --quick            # Quick: rebuild index.html from existing meta
  python paper_manager.py --dir ~/Papers     # Specify directory
  python paper_manager.py --dry-run          # Preview changes only
  python paper_manager.py --no-fetch         # Skip IEEE title fetching
        '''
    )
    parser.add_argument('--dir', '-d',
                        default='',
                        help='Base directory for papers (default: ~/Downloads/ieee_papers)')
    parser.add_argument('--dry-run', '-n',
                        action='store_true',
                        help='Preview changes without moving files')
    parser.add_argument('--no-fetch',
                        action='store_true',
                        help='Skip fetching titles from IEEE website')
    parser.add_argument('--max-size', '-s',
                        type=int,
                        default=MAX_PDF_SIZE_MB,
                        help=f'Max PDF size in MB to parse (default: {MAX_PDF_SIZE_MB})')
    parser.add_argument('--meta', '-m',
                        default='',
                        help='Path to paper_meta.json (default: BASE_DIR/paper_meta.json)')
    parser.add_argument('--verbose', '-v',
                        action='store_true',
                        help='Show per-file details (default: summary only)')
    parser.add_argument('--quick', '-q',
                        action='store_true',
                        help='Quick mode: rebuild index.html from existing meta only (no PDF scan)')
    return parser.parse_args()


def main():
    global BASE_DIR, MAX_PDF_SIZE_MB, INPUT_DIRS, META_FILE, HTML_FILE, BACKUP_DIR

    args = parse_args()

    # Override settings from command line
    if args.dir:
        INPUT_DIRS = [Path(os.path.expanduser(args.dir))]
        BASE_DIR = INPUT_DIRS[0]
        # Prefer the largest meta file (master copy has more entries)
        _meta_cands = [BASE_DIR / "scripts" / "paper_meta.json", BASE_DIR / "paper_meta.json", _SCRIPT_DIR / "paper_meta.json"]
        _meta_existing = [p for p in _meta_cands if p.exists()]
        if _meta_existing:
            META_FILE = max(_meta_existing, key=lambda p: p.stat().st_size)
        else:
            META_FILE = _meta_cands[0]
        HTML_FILE = BASE_DIR / "index.html"
        BACKUP_DIR = BASE_DIR / "_duplicates"
    if args.max_size:
        MAX_PDF_SIZE_MB = args.max_size
    if args.meta:
        META_FILE = Path(os.path.expanduser(args.meta))

    DRY_RUN = args.dry_run
    NO_FETCH = args.no_fetch
    VERBOSE = args.verbose

    t0 = time.time()
    print("=" * 60)
    print("IEEE Paper Manager v2 (optimized)")
    print("=" * 60)
    print(f"\nBase directory: {BASE_DIR}")
    print(f"Meta file: {META_FILE}")
    print(f"Max PDF size for parsing: {MAX_PDF_SIZE_MB}MB")
    if DRY_RUN:
        print("*** DRY RUN MODE - No files will be moved ***")
    if NO_FETCH:
        print("*** Skipping IEEE title fetching ***")

    QUICK = args.quick

    if not BASE_DIR.exists():
        print(f"ERROR: Directory not found: {BASE_DIR}")
        return

    # Quick mode: fast index rebuild with new-download merging
    if QUICK:
        print("\n[QUICK MODE] Rebuilding index from existing meta...")
        papers = {}

        # 1. Load master meta
        for entry in _load_meta_entries(META_FILE):
            _add_meta_entry(papers, entry)
        print(f"  Master: {len(papers)} papers")

        # 2. Merge paper_meta_new.json (Chrome extension new downloads)
        new_meta_file = BASE_DIR / "paper_meta_new.json"
        if new_meta_file.exists():
            new_count = 0
            for entry in _load_meta_entries(new_meta_file):
                did = entry.get('docId')
                if did and did not in papers:
                    _add_meta_entry(papers, entry)
                    new_count += 1
            if new_count > 0:
                print(f"  Merged: {new_count} new from paper_meta_new.json")
                new_meta_file.unlink()

        # 3. Scan disk for PDF files not in meta (by docId in filename)
        scanned_new = 0
        scan_dirs = [d for d in BASE_DIR.iterdir() if d.is_dir() and not d.name.startswith('_')]
        for cat_dir in scan_dirs:
            is_inbox = cat_dir.name == '0_inbox'
            is_known = cat_dir.name in STD_CATEGORIES
            if not is_inbox and not is_known:
                continue
            for pdf_file in cat_dir.glob('*.pdf'):
                did = extract_doc_id(pdf_file.name)
                if did and did not in papers:
                    year = extract_year(pdf_file.name) or ''
                    title = title_from_filename(pdf_file.name)
                    cat = categorize(title, filename=pdf_file.name) if is_inbox else cat_dir.name
                    papers[did] = {
                        'title': title, 'docId': did,
                        'new_category': cat, 'year': year,
                        'pdfUrl': f'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={did}',
                        'savePath': '', 'pdf_keywords': '',
                        'files': [], 'final_path': pdf_file,
                    }
                    scanned_new += 1
        if scanned_new > 0:
            print(f"  Scanned: {scanned_new} new from disk")

        # 4. Resolve PDF paths
        base_dirs = [BASE_DIR]
        if _SCRIPT_DIR.parent != BASE_DIR:
            base_dirs.append(_SCRIPT_DIR.parent)
        for did, p in papers.items():
            sp = p.get('savePath', '')
            if sp:
                candidate = BASE_DIR / sp.replace('ieee_papers/', '', 1)
                if candidate.exists():
                    p['final_path'] = candidate
            # Also try docId search
            if not p.get('final_path'):
                doc_id = p.get('docId', '')
                if doc_id and not doc_id.startswith('T_'):
                    cat = p.get('new_category', 'Others')
                    for bd in base_dirs:
                        cat_d = bd / cat
                        if cat_d.is_dir():
                            for f in cat_d.iterdir():
                                if f.is_file() and doc_id in f.name:
                                    p['final_path'] = f
                                    break
                        if p.get('final_path'):
                            break

        print(f"  Total: {len(papers)} papers")
        t0 = time.time()
        print("\n[7/7] Generating HTML search page...")
        generate_html(papers)
        elapsed = time.time() - t0
        print(f"  Generated: {HTML_FILE}")
        cat_counts = defaultdict(int)
        for p in papers.values():
            cat_counts[p.get('new_category') or p.get('category', 'Others')] += 1
        print("\n" + "=" * 60)
        print("Summary (quick)")
        print("=" * 60)
        cat_counts = defaultdict(int)
        for p in papers.values():
            cat = p.get('new_category') or p.get('category', 'Others')
            cat_counts[cat] += 1
        print(f"  Total papers: {len(papers)}")
        print(f"  Time: {elapsed:.1f}s")
        for cat in sorted(cat_counts):
            print(f"    {cat:20s} {cat_counts[cat]:3d}")
        print(f"  HTML: {HTML_FILE}")
        return

    # Step 1
    print("\n[1/7] Collecting papers...")
    papers = collect_papers()
    print(f"  Found {len(papers)} unique papers (by docId)")

    # Step 2
    if NO_FETCH:
        print("\n[2/7] Skipping IEEE title fetching (--no-fetch)")
        fetched = 0
    else:
        print("\n[2/7] Completing truncated titles from IEEE...")
        fetched = complete_titles(papers)
        print(f"  Fetched {fetched} full titles")

    # Step 3
    print("\n[3/7] Re-classifying and deduplicating...")
    stats = reclassify_and_dedup(papers, dry_run=DRY_RUN, verbose=VERBOSE)
    print(f"  Re-classified: {stats['reclassified']}")
    print(f"  Duplicates removed: {stats['duplicates_removed']}")
    print(f"  Papers with keywords: {stats['keywords_used']}")

    # Step 4
    print("\n[4/7] Reorganizing files...")
    moved = reorganize_files(papers, dry_run=DRY_RUN, verbose=VERBOSE)
    print(f"  {'Would move' if DRY_RUN else 'Moved'} {moved} files")

    # Step 5
    if DRY_RUN:
        print("\n[5/7] Skipping cleanup (dry-run)")
    else:
        print("\n[5/7] Cleaning up empty folders...")
        cleanup_empty_dirs()

    # Step 6
    if DRY_RUN:
        print("\n[6/7] Skipping meta update (dry-run)")
        total = len(papers)
    else:
        print("\n[6/7] Updating paper_meta.json...")
        total = update_meta(papers)
        print(f"  Saved {total} entries")
        # Clean up merged new-download meta
        new_meta = BASE_DIR / "paper_meta_new.json"
        if new_meta.exists():
            new_meta.unlink()
            safe_print(f"  Cleaned up paper_meta_new.json (merged)")

    # Step 7
    if DRY_RUN:
        print("\n[7/7] Skipping HTML generation (dry-run)")
    else:
        print("\n[7/7] Generating HTML search page...")
        generate_html(papers)
        print(f"  Generated: {HTML_FILE}")
    print(f"  Generated: {HTML_FILE}")

    # Summary
    elapsed = time.time() - t0
    cat_counts = defaultdict(int)
    for p in papers.values():
        cat_counts[p.get('new_category') or p.get('category', 'Others')] += 1
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total papers: {len(papers)}")
    print(f"  Time elapsed: {elapsed:.1f}s")
    print(f"  Categories:")
    for cat in sorted(cat_counts.keys()):
        print(f"    {cat:20s} {cat_counts[cat]:3d}")
    print(f"\n  HTML search page: {HTML_FILE}")
    print(f"  Open in browser to search and filter papers.")
    if stats['duplicates_removed'] > 0:
        print(f"  Duplicates moved to: {BACKUP_DIR}")

    if IMPORTED_FOLDERS:
        print("\n" + "-" * 60)
        safe_print("IMPORTED FOLDERS (now processed)")
        print("-" * 60)
        remaining = []
        for folder in IMPORTED_FOLDERS:
            if folder.exists():
                remaining.append(folder)
                print(f"  {folder.name}/")
        if remaining:
            print(f"\n  These folders may now be empty.")
            print(f"  You can safely delete them manually if no longer needed.")
        else:
            print("  All imported folders have been cleaned up automatically.")

    if MANUAL_REVIEW:
        print("\n" + "=" * 60)
        safe_print("FILES NEEDING MANUAL REVIEW")
        print("=" * 60)
        print(f"  {len(MANUAL_REVIEW)} files could not be processed automatically:")
        for i, item in enumerate(MANUAL_REVIEW[:10], 1):
            print(f"\n  {i}. {Path(item['file']).name[:80]}")
            print(f"     Reason: {item['reason']}")
        if len(MANUAL_REVIEW) > 10:
            print(f"\n  ... and {len(MANUAL_REVIEW) - 10} more files")

        review_file = BASE_DIR / "_manual_review.json"
        with open(review_file, 'w', encoding='utf-8') as f:
            json.dump(MANUAL_REVIEW, f, indent=2, ensure_ascii=False)
        print(f"\n  Full report saved to: {review_file}")
    print()


if __name__ == '__main__':
    main()
