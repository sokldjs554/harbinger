"""Compare installed image package bytes with checked-out source, without secrets."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--container", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    expected = {
        str(f.relative_to("src/harbinger")): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(Path("src/harbinger").rglob("*"))
        if f.is_file() and f.suffix in (".py", ".js", ".css", ".html")
    }
    program = """import hashlib,json,pathlib,harbinger
root=pathlib.Path(harbinger.__file__).parent
print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.html')}))"""
    actual = json.loads(
        subprocess.check_output(["docker", "exec", a.container, "python", "-c", program], text=True)
    )
    assert actual == expected, {
        "missing": sorted(expected.keys() - actual.keys()),
        "different": [k for k in expected if actual.get(k) != expected[k]],
    }
    image = subprocess.check_output(
        ["docker", "inspect", a.container, "--format", "{{.Image}}"], text=True
    ).strip()
    uid = subprocess.check_output(["docker", "exec", a.container, "id", "-u"], text=True).strip()
    assert uid == "10001"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        json.dumps(
            {"image": image, "uid": uid, "source_files_verified": len(expected), "sha256": expected}, indent=2
        )
    )
    print(f"Image source parity verified: {len(expected)} files, UID {uid}")


if __name__ == "__main__":
    main()
