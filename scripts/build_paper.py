"""Build a historical-evidence manuscript; never run the scientific experiment."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    for script in ('check_evidence.py', 'paper_extract.py', 'paper_ledger.py'):
        subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], cwd=ROOT, check=True)
    tex = shutil.which('pdflatex') or '/Library/TeX/texbin/pdflatex'
    bib = shutil.which('bibtex') or '/Library/TeX/texbin/bibtex'
    if not Path(tex).is_file() or not Path(bib).is_file():
        raise SystemExit('Install TeX Live with pdflatex and bibtex; this formats archived evidence only')
    output = ROOT / 'paper/build'
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['SOURCE_DATE_EPOCH'] = '1791244800'
    command = [tex, '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
               '-output-directory', str(output), 'main.tex']
    for step in range(3):
        result = subprocess.run(command, cwd=ROOT / 'paper', env=env, capture_output=True, text=True)
        (output / f'pdflatex-{step + 1}.txt').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise SystemExit(result.stdout[-5000:] + result.stderr)
        if step == 0:
            bibenv = env | {'BIBINPUTS': str(ROOT / 'paper') + os.pathsep}
            result = subprocess.run([bib, 'main'], cwd=output, env=bibenv, capture_output=True, text=True)
            (output / 'bibtex.txt').write_text(result.stdout + result.stderr)
            if result.returncode:
                raise SystemExit(result.stdout + result.stderr)
    pdf = output / 'main.pdf'
    if not pdf.read_bytes().startswith(b'%PDF-'):
        raise SystemExit('Missing valid PDF')
    log = (output / 'main.log').read_text()
    warnings = [line for line in log.splitlines() if any(x in line for x in ('LaTeX Warning', 'Overfull', 'undefined'))]
    inputs = [ROOT / 'paper/main.tex', ROOT / 'paper/references.bib', ROOT / 'downloads/rhomax-wavelength-results.tar.gz']
    inputs += sorted((ROOT / 'paper/generated').glob('*.tex'))
    inputs += sorted((ROOT / 'article/assets').glob('*.png'))
    receipt = {
        'kind': 'historical evidence formatting; no new scientific computation',
        'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_worktree_clean': not bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'engine': subprocess.check_output([tex, '--version'], text=True).splitlines()[0],
        'bibliography_engine': subprocess.check_output([bib, '--version'], text=True).splitlines()[0],
        'source_date_epoch': env['SOURCE_DATE_EPOCH'],
        'inputs': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
        'warnings': warnings,
    }
    (output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    if warnings:
        raise SystemExit('Review LaTeX warnings: ' + '\n'.join(warnings))
    print(pdf)

if __name__ == '__main__':
    main()
