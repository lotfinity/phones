#!/usr/bin/env bash
set -u

TS="$(date +%Y%m%d_%H%M%S)"
OUT="reports/catalog_transition_audit_${TS}.log"

echo "Writing full output to: $OUT"
echo "Started at: $(date)" > "$OUT"
echo "Repo: $(pwd)" >> "$OUT"
echo "Branch: $(git branch --show-current 2>/dev/null || true)" >> "$OUT"
echo "Commit: $(git rev-parse --short HEAD 2>/dev/null || true)" >> "$OUT"
echo "" >> "$OUT"

run_cmd() {
  echo "" >> "$OUT"
  echo "================================================================================" >> "$OUT"
  echo "$ $*" >> "$OUT"
  echo "================================================================================" >> "$OUT"
  "$@" >> "$OUT" 2>&1
  STATUS=$?
  echo "" >> "$OUT"
  echo "Exit status: $STATUS" >> "$OUT"
  return $STATUS
}

run_cmd python manage.py audit_catalog_transition
run_cmd python manage.py backfill_variant_specs --dry-run
run_cmd python manage.py backfill_listing_specs --dry-run --set-product-type
run_cmd python manage.py recompute_listing_matches --product-type phone --dry-run
run_cmd python manage.py recompute_listing_matches --product-type laptop --dry-run

echo "" >> "$OUT"
echo "Finished at: $(date)" >> "$OUT"

echo ""
echo "Done. Full log saved to:"
echo "$OUT"
echo ""
echo "Preview last 80 lines:"
tail -n 80 "$OUT"
