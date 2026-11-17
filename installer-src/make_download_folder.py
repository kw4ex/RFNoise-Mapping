"""Builds the download folder for one release, laid out like the other programs in C:\\RadioScripts\\KW4EX_Downloads:
   <out>/RFNoise_Mapping_v<version>/  Install_RFNoise_Windows.bat, Uninstall_RFNoise_Mapping.bat, README_RFNoise.txt,
   RFNoise_Help.html, RFNoise_User_Guide.pdf, LICENSE.txt, Release_Notes.md, Mac/ (the three Mac files).
   Run build_installer.py and make_guide_pdf.py first."""
import os, re, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
ver = re.search(r'^VERSION = "([\w.]+)"', open(os.path.join(REPO, "app", "rfmap_common.py"), encoding="utf-8").read(), re.M).group(1)
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "dist")
dst = os.path.join(out, "RFNoise_Mapping_v" + ver)
if os.path.isdir(dst): shutil.rmtree(dst)
os.makedirs(os.path.join(dst, "Mac"))
def crlf_copy(src, to):
    d = open(src, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"); open(to, "wb").write(d)
shutil.copy(os.path.join(REPO, "Install_RFNoise_Windows.bat"), dst)
crlf_copy(os.path.join(HERE, "standalone", "Uninstall_RFNoise_Mapping.bat"), os.path.join(dst, "Uninstall_RFNoise_Mapping.bat"))
crlf_copy(os.path.join(HERE, "payload", "README_RFNoise.txt"), os.path.join(dst, "README_RFNoise.txt"))
crlf_copy(os.path.join(HERE, "payload", "LICENSE.txt"), os.path.join(dst, "LICENSE.txt"))
shutil.copy(os.path.join(REPO, "app", "guide.html"), os.path.join(dst, "RFNoise_Help.html"))
shutil.copy(os.path.join(REPO, "docs", "guides", "RFNoise-Mapping-guide.pdf"), os.path.join(dst, "RFNoise_User_Guide.pdf"))
rn = os.path.join(REPO, "docs", "release-notes", "v" + ".".join(ver.split(".")[:2]) + ".0.md")
if os.path.exists(rn): shutil.copy(rn, os.path.join(dst, "Release_Notes.md"))
for f in os.listdir(os.path.join(REPO, "mac")):
    shutil.copy(os.path.join(REPO, "mac", f), os.path.join(dst, "Mac", f))
print(dst); [print("  ", n, os.path.getsize(os.path.join(dst, n)) if os.path.isfile(os.path.join(dst, n)) else "(folder)") for n in sorted(os.listdir(dst))]
