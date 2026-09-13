#!/usr/bin/env python3
"""한국어 공개 원본을 고정 URL로 수집한다. 발화 내용은 출력하지 않는다."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from public_data import data_root, download, extract_tar

FLEURS_REV = '70bb2e84b976b7e960aa89f1c648e09c59f894dd'
HF = f'https://huggingface.co/datasets/google/fleurs/resolve/{FLEURS_REV}'
SLR = 'https://www.openslr.org/resources'
ASSETS = {
    'fleurs-ko': [
        (f'{HF}/data/ko_kr/audio/{s}.tar.gz', f'{s}.tar.gz', h)
        for s, h in [('dev', '496edcb5323e75b4a2830f5b5623684a0baf86d3728101853fd4fe503372157c'),
                     ('test', '3489e529f2aad18d3357b746c5f955941d258b79dc60d8a102d5bced2a223184'),
                     ('train', '985d45a1ab3967f6851761bac8f7f325360eba3381ffed96f9ce920d3c24e9d9')]]
        + [(f'{HF}/data/ko_kr/{s}.tsv', f'{s}.tsv', None) for s in ('dev', 'test', 'train')]
        + [(f'{HF}/README.md', 'SOURCE-README.md', None)],
    'seoul': [(f'{SLR}/113/{name}', name, None) for name in ('readme.tgz', 'label.tgz', 'sound.tgz')],
    'deeply': [(f'{SLR}/97/KoreanReadSpeechCorpus.tar.gz', 'KoreanReadSpeechCorpus.tar.gz', None),
               ('https://raw.githubusercontent.com/deeplyinc/Korean-Read-Speech-Corpus/1c9cdb8ca1ba79bf982c97b16fb40657420c9cba/dataset/Korean_Read_Speech_Corpus_sample.json',
                'Korean_Read_Speech_Corpus_sample.json', None)],
    'pansori': [(f'{SLR}/58/pansori-tedxkr-corpus-1.0.tar.gz', 'pansori-tedxkr-corpus-1.0.tar.gz', None)],
    'zeroth': [(f'{SLR}/40/zeroth_korean.tar.gz', 'zeroth_korean.tar.gz', None)],
}
for dataset, slr_id in [('seoul', 113), ('deeply', 97), ('pansori', 58), ('zeroth', 40)]:
    ASSETS[dataset].append((f'https://www.openslr.org/{slr_id}/', 'SOURCE.html', None))


def collect(root, dataset, asset, extract, connections=1):
    url, filename, checksum = asset
    base = root / 'public' / dataset
    target = base / 'raw' / filename
    receipt = download(url, target, checksum,
                       connections=connections if filename.endswith(('.tar.gz', '.tgz')) else 1)
    print(f'{dataset}/{filename}: {receipt["bytes"]:,} bytes 검증', flush=True)
    if extract and filename.endswith(('.tar.gz', '.tgz')):
        folder = filename.removesuffix('.tar.gz').removesuffix('.tgz')
        extract_tar(target, base / 'extracted' / folder,
                    include_roots=('test_data_01', 'train_data_01', 'AUDIO_INFO') if dataset == 'zeroth' else None)
        print(f'{dataset}/{filename}: 압축 해제 완료', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path)
    ap.add_argument('--datasets', nargs='+', choices=ASSETS, default=list(ASSETS))
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--connections', type=int, default=1, help='대형 원본별 HTTP Range 연결 수(1~32)')
    args = ap.parse_args()
    root = data_root(args.root)
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        jobs = {pool.submit(collect, root, dataset, asset, args.extract, args.connections): (dataset, asset[1])
                for dataset in args.datasets for asset in ASSETS[dataset]}
        for future in as_completed(jobs):
            try:
                future.result()
            except Exception as exc:
                dataset, name = jobs[future]
                failures.append((dataset, name, type(exc).__name__))
                print(f'{dataset}/{name}: 실패 ({type(exc).__name__}: {exc})', flush=True)
    if failures:
        raise SystemExit(f'{len(failures)}개 수집/해제 실패. 완성 자료는 보존되며 재실행 가능.')


if __name__ == '__main__':
    main()
