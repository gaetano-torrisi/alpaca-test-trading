#!/usr/bin/env bash
# Giro continuo: esegue i due bot ogni 15 minuti durante la seduta USA (lun-ven 13-22 UTC),
# il report serale una volta al giorno, e si ferma dopo ~5h40m (poi il workflow si riavvia da solo).
set -u
END=$(( $(date +%s) + ${MOTORE_DURATA:-20400} ))
git config user.name "trading-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

salva() {
  for d in log state report; do if [ -e "$d" ]; then git add -A "$d"; fi; done
  if ! git diff --cached --quiet; then
    git commit -q -m "$1"
    for i in 1 2 3; do git pull -q --rebase && git push -q && break; sleep 5; done
  fi
}

while [ "$(date +%s)" -lt "$END" ]; do
  DOW=$(date -u +%u); H=$((10#$(date -u +%H))); M=$((10#$(date -u +%M)))
  if [ "$DOW" -le 5 ] && [ "$H" -ge 13 ] && [ "$H" -le 21 ]; then
    git pull -q --rebase || true
    echo "=== $(date -u +'%F %H:%M') UTC – Test Trading"
    ALPACA_API_KEY="$MAIN_KEY" ALPACA_SECRET_KEY="$MAIN_SECRET" BOT_NAME="" BOT_CONFIG="config.yaml" \
      python -m tbot.live || true
    echo "=== $(date -u +'%F %H:%M') UTC – Test Tech"
    ALPACA_API_KEY="$TECH_KEY" ALPACA_SECRET_KEY="$TECH_SECRET" BOT_NAME="tech" BOT_CONFIG="config_tech.yaml" \
      python -m tbot.live || true
    salva "bot: giro $(date -u +'%Y-%m-%d %H:%M') UTC"
  fi
  # report serale (dopo la chiusura USA), una volta per giorno di borsa
  OGGI=$(date -u +%F)
  if [ "$DOW" -le 5 ] && [ $((H*60+M)) -ge $((21*60+15)) ] && [ "$(cat state/ultimo_report 2>/dev/null)" != "$OGGI" ]; then
    git pull -q --rebase || true
    ALPACA_API_KEY="$MAIN_KEY" ALPACA_SECRET_KEY="$MAIN_SECRET" BOT_NAME="" BOT_CONFIG="config.yaml" python -m tbot.report >/dev/null || true
    ALPACA_API_KEY="$TECH_KEY" ALPACA_SECRET_KEY="$TECH_SECRET" BOT_NAME="tech" BOT_CONFIG="config_tech.yaml" python -m tbot.report >/dev/null || true
    echo "$OGGI" > state/ultimo_report
    salva "report $OGGI"
  fi
  # attende il prossimo quarto d'ora
  NOW=$(date +%s); NEXT=$(( (NOW/900 + 1) * 900 + 30 ))
  [ "$NEXT" -ge "$END" ] && break
  sleep $(( NEXT - NOW ))
done
echo "Fine turno del motore: $(date -u +'%F %H:%M') UTC"
