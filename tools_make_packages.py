"""Builds the two download packages (Mac and Windows) from the repository.  Usage: python3 tools_make_packages.py OUTDIR"""
import os, re, sys, shutil, zipfile, stat, subprocess
R = os.path.dirname(os.path.abspath(__file__)); OUT = sys.argv[1]
ver = re.search(r'VERSION\s*=\s*"([^"]+)"', open(os.path.join(R, "app", "nt_common.py")).read()).group(1)
def ignore(d, names): return [n for n in names if n in ("__pycache__",) or n.endswith(".pyc")]
def zipdir(folder, zpath):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            for f in sorted(files):
                full = os.path.join(root, f); arc = os.path.relpath(full, os.path.dirname(folder))
                zi = zipfile.ZipInfo.from_file(full, arc); zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = (0o100755 if f.endswith((".command", ".sh")) else 0o100644) << 16
                with open(full, "rb") as fh: z.writestr(zi, fh.read())
def make_guide_pdf(dest_dir):
    """RFI_Trail_Help.html (a copy of the guide) and RFI_Trail_User_Guide.pdf (printed from it with headless Chrome)."""
    g = os.path.join(R, "app", "guide.html")
    shutil.copy(g, os.path.join(dest_dir, "RFI_Trail_Help.html"))
    out = os.path.join(dest_dir, "RFI_Trail_User_Guide.pdf")
    for chrome in ("/usr/bin/google-chrome", "google-chrome", "chromium", "chromium-browser"):
        try:
            subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + out, "file://" + g],
                           capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if os.path.exists(out) and os.path.getsize(out) > 50000: return
    raise SystemExit("could not make the guide PDF (needs Chrome)")
def build(kind):
    name = "RFI_Trail_%s_v%s" % (kind, ver); d = os.path.join(OUT, name)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    shutil.copytree(os.path.join(R, "app"), os.path.join(d, "app"), ignore=ignore)
    shutil.copy(os.path.join(R, "LICENSE"), os.path.join(d, "LICENSE"))
    src = os.path.join(R, "mac" if kind == "Mac" else "windows")
    shutil.copytree(src, os.path.join(d, "mac" if kind == "Mac" else "windows"), ignore=ignore) if kind == "Mac" else None
    if kind == "Windows":
        for f in os.listdir(src):
            data = open(os.path.join(src, f), "rb").read()
            if f.endswith(".bat"): data = data.replace(b"__VER__", ver.encode())
            if f == "README_Windows.txt": data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            open(os.path.join(d, f), "wb").write(data)
    start = open(os.path.join(R, "START_HERE_%s.txt" % kind), encoding="utf-8").read().replace("__VER__", ver)
    open(os.path.join(d, "START_HERE.txt"), "w", encoding="utf-8", newline="\r\n" if kind == "Windows" else "\n").write(start)
    if kind == "Mac":
        for f in os.listdir(os.path.join(d, "mac")):
            if f.endswith(".command"): os.chmod(os.path.join(d, "mac", f), 0o755)
    make_guide_pdf(d)
    zipdir(d, d + ".zip"); print(name, "->", d + ".zip", os.path.getsize(d + ".zip") // 1024, "KB")
os.makedirs(OUT, exist_ok=True); build("Mac"); build("Windows")
