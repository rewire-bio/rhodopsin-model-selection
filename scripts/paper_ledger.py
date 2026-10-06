"""Map historical manuscript numbers to immutable archived result fields."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'downloads/rhomax-wavelength-results.tar.gz'
PREFIX = 'rhomax-wavelength-results/'
NAMES = {'training-mean': 'Training mean', 'composition-22': 'Composition-22',
         'composition-40': 'Composition-40', 'nearest-train-seq': 'Nearest sequence',
         'esm2-8m': 'ESM-2 8M', 'esm2-35m': 'ESM-2 35M'}

def main():
    with tarfile.open(ARCHIVE) as archive:
        raw = {name: archive.extractfile(PREFIX + name).read() for name in
               ('panel-receipt.json', 'exploratory-analysis.json', 'diagnostics.json',
                'ndcg-finite-reference.json', 'device-agreement.json')}
    values = {name: json.loads(body) for name, body in raw.items()}
    scores = values['panel-receipt.json']['scores']
    gen = ROOT / 'paper/generated'
    gen.mkdir(exist_ok=True, parents=True)
    lines = []
    for name, label in NAMES.items():
        s = scores[name]
        rho = 'undefined' if s['spearman'] is None else f"{s['spearman']:+.3f}"
        lines.append(f"{label} & {s['mae_nm']:.2f} & {s['rmse_nm']:.2f} & {rho} & {s['ndcg']:.4f} " + r'\\')
    (gen / 'tab_main_compact.tex').write_text('\n'.join(lines) + '\n')
    macros = {'CompMAE': scores['composition-22']['mae_nm'],
              'MeanMAE': scores['training-mean']['mae_nm'],
              'GainMAE': scores['training-mean']['mae_nm'] - scores['composition-22']['mae_nm']}
    (gen / 'paper_macros.tex').write_text(''.join(
        f'\\newcommand{{\\{key}}}{{{value:.2f}}}\n' for key, value in macros.items()))
    claims = []
    # Object-valued evidence records retain every number in the generated table family.
    mapping = {
        'panel-receipt.json': ['scores', 'reproduction_vs_archive', 'timings_seconds',
                               'environment', 'source', 'nearest_neighbour_fallbacks',
                               'total_wall_seconds', 'peak_rss_mb'],
        'exploratory-analysis.json': ['grouping', 'paired_bootstrap_vs_training-mean',
                                      'distance_bins', 'per_group', 'shortlists',
                                      'random_reference', 'post_hoc'],
        'diagnostics.json': ['prediction_spread', 'fixed_alpha_is_not_fixed_regularisation',
                             'chance_level_for_a_red_shifted_hit'],
        'ndcg-finite-reference.json': list(values['ndcg-finite-reference.json']),
        'device-agreement.json': list(values['device-agreement.json']),
    }
    for member, pointers in mapping.items():
        for pointer in pointers:
            claims.append({'id': f'{member}:{pointer}', 'kind': 'historical-evidence',
                           'archive_member': PREFIX + member, 'result_pointer': pointer,
                           'value': values[member][pointer],
                           'member_sha256': hashlib.sha256(raw[member]).hexdigest()})
    ledger = {'schema_version': 1, 'status': 'imported historical measurements; not harness-verified',
              'archive': str(ARCHIVE.relative_to(ROOT)),
              'archive_sha256': hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
              'claims': claims,
              'interpretations': [
                  {'claim': 'Composition rank advantage yields little absolute-error gain on this split',
                   'based_on': ['panel-receipt.json:scores', 'exploratory-analysis.json:paired_bootstrap_vs_training-mean'],
                   'limits': 'Fixed configurations; exploratory reconstructed-group intervals; no tuned family comparison'},
                  {'claim': 'Different shortlist objectives produce different selected rows',
                   'based_on': ['exploratory-analysis.json:shortlists', 'exploratory-analysis.json:post_hoc'],
                   'limits': 'Post-hoc spread intervals; observed test population only'},
                  {'claim': 'Coverage under independent background shifts is unestablished',
                   'based_on': ['exploratory-analysis.json:post_hoc'],
                   'limits': 'Single validation/test split; row-level Wilson intervals omit group dependence'}]}
    (gen / 'historical-claims.json').write_text(json.dumps(ledger, indent=2, sort_keys=True) + '\n')
    print(f'Mapped {len(claims)} historical result fields to archive members')

if __name__ == '__main__':
    main()
