#!/bin/bash
# Cloudflare Pages 빌드 스크립트 — public-safe 파일만 dist/ 로 추출.
# 소스 코드 (src/, communities/, data/, dev/, analysis/) 는 deploy 안 됨.
#
# Cloudflare Pages 설정:
#   Build command:           bash scripts/build-pages.sh
#   Build output directory:  dist
#   Root directory:          (비움)
#
# 로컬에서 미리보기:
#   bash scripts/build-pages.sh
#   python3 -m http.server 8888 -d dist/   # → http://localhost:8888/

set -euo pipefail

DIST="dist"
echo "=== Building Cloudflare Pages bundle ==="
rm -rf "$DIST"
mkdir -p "$DIST/docs"

# 루트 HTML (인터랙티브 오버뷰 + 기여자 온보딩)
cp index.html "$DIST/"
cp START_HERE.html "$DIST/"

# docs/ 에서 deploy 할 것들
cp docs/onboarding.html "$DIST/docs/"
cp -r docs/screenshots "$DIST/docs/"

# 통계
FILES=$(find "$DIST" -type f | wc -l | tr -d ' ')
SIZE=$(du -sh "$DIST" | cut -f1)
echo "=== Done — $FILES files, $SIZE ==="
echo
echo "Deploy 대상 (public 노출):"
find "$DIST" -type f | sed 's|^|  |' | sort
echo
echo "Public URLs (배포 후):"
echo "  /                      → index.html"
echo "  /START_HERE.html"
echo "  /docs/onboarding.html"
echo "  /docs/screenshots/*.{png,webp}"
echo
echo "Private 유지 (deploy X): src/ · communities/ · data/ · dev/ · analysis/ · .env · *.db"
