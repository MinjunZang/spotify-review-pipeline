#!/bin/bash
# Full-corpus enrichment with interruption/resume evidence.
#   ./run_full.sh start    first run (phase=initial); press Ctrl+C after a minute or two
#   ./run_full.sh resume   continue (phase=resume); completed IDs are never re-sent
#   ./run_full.sh status   record counts by status
cd "$(dirname "$0")"
DB=work/full/pipeline.sqlite
RUN=outputs/runs/full
status() { echo "--- record status ($(date +%H:%M:%S))"; sqlite3 "$DB" "select status, count(*) from status group by status"; }
case "$1" in
  start)  status; caffeinate -i python3 -m pipeline.enrich --db $DB --run-dir $RUN --workers 8 --budget 15 \
            --max-output-tokens 6000 --phase initial --snapshot $RUN/checkpoints/checkpoint_before.json; status ;;
  resume) status; caffeinate -i python3 -m pipeline.enrich --db $DB --run-dir $RUN --workers 8 --budget 15 \
            --max-output-tokens 6000 --phase resume --snapshot $RUN/checkpoints/checkpoint_after.json; status ;;
  status) status ;;
  *) echo "usage: ./run_full.sh start|resume|status" ;;
esac
