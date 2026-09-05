#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
POSTGRES_ENV_FILE="$PROJECT_DIR/.env.postgres"
BACKUP_DIR="${DB_BACKUP_DIR:-$PROJECT_DIR/backups}"
LATEST_BACKUP="$BACKUP_DIR/bot-latest.db"
PREVIOUS_BACKUP="$BACKUP_DIR/bot-previous.db"
TMP_BACKUP="$BACKUP_DIR/.bot-latest.db.tmp"
LATEST_PG_DUMP="$BACKUP_DIR/postgres-latest.dump"
PREVIOUS_PG_DUMP="$BACKUP_DIR/postgres-previous.dump"
TMP_PG_DUMP="$BACKUP_DIR/.postgres-latest.dump.tmp"
LATEST_ARCHIVE="$BACKUP_DIR/bot-latest.tar.gz"
TMP_ARCHIVE="$BACKUP_DIR/.bot-latest.tar.gz.tmp"
PARTS_DIR="$BACKUP_DIR/telegram-parts"
LOCK_FILE="$BACKUP_DIR/.backup.lock"
TELEGRAM_DOCUMENT_MAX_BYTES="${TELEGRAM_DOCUMENT_MAX_BYTES:-47185920}"

read_env_file_value() {
    local env_file="$1"
    local key="$2"
    local line=""
    local value=""

    if [ ! -f "$env_file" ]; then
        return 0
    fi

    line="$(grep -E "^[[:space:]]*${key}=" "$env_file" | tail -n 1 || true)"
    if [ -z "$line" ]; then
        return 0
    fi

    value="${line#*=}"
    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
}

read_env_value() {
    local key="$1"
    local value=""

    value="$(read_env_file_value "$POSTGRES_ENV_FILE" "$key")"
    if [ -n "$value" ]; then
        printf '%s' "$value"
        return 0
    fi

    read_env_file_value "$ENV_FILE" "$key"
}

mkdir -p "$BACKUP_DIR" "$PROJECT_DIR/logs"

send_document() {
    local bot_token="$1"
    local chat_id="$2"
    local file_path="$3"
    local file_name="$4"
    local caption="$5"
    local response_file="$BACKUP_DIR/.telegram-response-${chat_id}.json"

    if curl -fsS --retry 3 --retry-delay 5 --connect-timeout 20 --max-time 600 \
        -X POST "https://api.telegram.org/bot${bot_token}/sendDocument" \
        -F "chat_id=${chat_id}" \
        -F "document=@${file_path};filename=${file_name}" \
        -F "caption=${caption}" \
        -o "$response_file"; then
        if grep -q '"ok":true' "$response_file"; then
            rm -f "$response_file"
            return 0
        fi
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') telegram send failed for admin $chat_id: $(head -c 500 "$response_file" 2>/dev/null || true)" >&2
    rm -f "$response_file"
    return 1
}

send_archive_to_admins() {
    local archive_path="$1"
    local archive_name="$2"
    local created_at="$3"
    local bot_token="${BOT_TOKEN:-$(read_env_value BOT_TOKEN)}"
    local admin_ids="${ADMIN_IDS:-$(read_env_value ADMIN_IDS)}"
    local archive_size=""
    local admin_id=""
    local failures=0
    local valid_admins=0
    local part_files=()
    local part_count=0
    local part_index=0
    local part_file=""
    local part_name=""
    local caption=""
    local archive_sha256=""

    if [ -z "$bot_token" ] || [ -z "$admin_ids" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') telegram send skipped: BOT_TOKEN or ADMIN_IDS is empty" >&2
        return 1
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') telegram send skipped: curl not found" >&2
        return 1
    fi

    archive_size="$(du -h "$archive_path" | awk '{print $1}')"
    if command -v sha256sum >/dev/null 2>&1; then
        archive_sha256="$(sha256sum "$archive_path" | awk '{print $1}')"
    else
        archive_sha256="sha256sum not available"
    fi
    caption="HappyFox DB backup
created: ${created_at}
archive: ${archive_size}
sha256: ${archive_sha256}
source: ${db_abs}"

    if [ "$(stat -c '%s' "$archive_path")" -le "$TELEGRAM_DOCUMENT_MAX_BYTES" ]; then
        IFS=',' read -ra admin_array <<< "$admin_ids"
        for admin_id in "${admin_array[@]}"; do
            admin_id="${admin_id//[[:space:]]/}"
            if [[ ! "$admin_id" =~ ^-?[0-9]+$ ]]; then
                continue
            fi
            valid_admins=$((valid_admins + 1))
            send_document "$bot_token" "$admin_id" "$archive_path" "$archive_name" "$caption" || failures=1
        done
    else
        if ! command -v split >/dev/null 2>&1; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') telegram send skipped: split not found and archive is too large" >&2
            return 1
        fi

        mkdir -p "$PARTS_DIR"
        find "$PARTS_DIR" -type f -name "${archive_name}.part-*" -delete
        split -b "$TELEGRAM_DOCUMENT_MAX_BYTES" -d -a 3 "$archive_path" "$PARTS_DIR/${archive_name}.part-"
        mapfile -t part_files < <(find "$PARTS_DIR" -type f -name "${archive_name}.part-*" | sort)
        part_count="${#part_files[@]}"

        IFS=',' read -ra admin_array <<< "$admin_ids"
        for admin_id in "${admin_array[@]}"; do
            admin_id="${admin_id//[[:space:]]/}"
            if [[ ! "$admin_id" =~ ^-?[0-9]+$ ]]; then
                continue
            fi
            valid_admins=$((valid_admins + 1))
            part_index=0
            for part_file in "${part_files[@]}"; do
                part_index=$((part_index + 1))
                part_name="$(basename "$part_file")"
                caption="HappyFox DB backup
created: ${created_at}
archive: ${archive_size}
part: ${part_index}/${part_count}
join: cat ${archive_name}.part-* > ${archive_name}
sha256: ${archive_sha256}"
                send_document "$bot_token" "$admin_id" "$part_file" "$part_name" "$caption" || failures=1
            done
        done
    fi

    if [ "$valid_admins" -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') telegram send skipped: no valid ADMIN_IDS" >&2
        return 1
    fi

    return "$failures"
}

(
    flock -n 9 || {
        echo "$(date '+%Y-%m-%d %H:%M:%S') backup already running"
        exit 0
    }

    created_at="$(date '+%Y-%m-%d %H:%M:%S %Z')"
    archive_name="happyfox-db-$(date '+%Y%m%d_%H%M%S').tar.gz"
    db_url="${DATABASE_URL:-$(read_env_value DATABASE_URL)}"
    db_path="${DATABASE_PATH:-$(read_env_value DATABASE_PATH)}"
    archive_member=""
    db_abs=""

    case "$db_url" in
        postgres://*|postgresql://*)
            if ! command -v pg_dump >/dev/null 2>&1; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup failed: pg_dump not found" >&2
                exit 1
            fi
            if ! command -v pg_restore >/dev/null 2>&1; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup failed: pg_restore not found" >&2
                exit 1
            fi

            rm -f "$TMP_PG_DUMP"
            mapfile -t pg_params < <(python3 - "$db_url" <<'PY'
from urllib.parse import unquote, urlparse
import sys

parsed = urlparse(sys.argv[1])
if parsed.scheme not in {"postgres", "postgresql"}:
    raise SystemExit("unsupported postgres url")

print(parsed.hostname or "")
print(str(parsed.port or ""))
print(unquote(parsed.username or ""))
print(unquote(parsed.password or ""))
print(unquote((parsed.path or "").lstrip("/")))
print(parsed.query or "")
PY
)
            pg_host="${pg_params[0]}"
            pg_port="${pg_params[1]}"
            pg_user="${pg_params[2]}"
            pg_password="${pg_params[3]}"
            pg_database="${pg_params[4]}"
            pg_query="${pg_params[5]}"
            pg_args=(--format=custom --no-owner --no-privileges --file "$TMP_PG_DUMP")

            if [ -n "$pg_host" ]; then
                pg_args+=(--host "$pg_host")
            fi
            if [ -n "$pg_port" ]; then
                pg_args+=(--port "$pg_port")
            fi
            if [ -n "$pg_user" ]; then
                pg_args+=(--username "$pg_user")
            fi
            if [ -n "$pg_database" ]; then
                pg_args+=(--dbname "$pg_database")
            fi
            if [[ "$pg_query" == *sslmode=* ]]; then
                PGSSLMODE="$(python3 - "$pg_query" <<'PY'
from urllib.parse import parse_qs
import sys
print(parse_qs(sys.argv[1]).get("sslmode", [""])[0])
PY
)"
                export PGSSLMODE
            fi

            if ! PGPASSWORD="$pg_password" pg_dump "${pg_args[@]}"; then
                rm -f "$TMP_PG_DUMP"
                echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup failed: pg_dump returned non-zero" >&2
                exit 1
            fi

            if [ ! -s "$TMP_PG_DUMP" ]; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup failed: empty dump" >&2
                rm -f "$TMP_PG_DUMP"
                exit 1
            fi

            if ! pg_restore --list "$TMP_PG_DUMP" >/dev/null; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup failed: pg_restore could not read dump" >&2
                rm -f "$TMP_PG_DUMP"
                exit 1
            fi

            if [ -f "$LATEST_PG_DUMP" ]; then
                cp -f "$LATEST_PG_DUMP" "$PREVIOUS_PG_DUMP"
            fi

            mv -f "$TMP_PG_DUMP" "$LATEST_PG_DUMP"
            archive_member="$(basename "$LATEST_PG_DUMP")"
            db_abs="postgres DATABASE_URL"

            size="$(du -h "$LATEST_PG_DUMP" | awk '{print $1}')"
            echo "$(date '+%Y-%m-%d %H:%M:%S') postgres backup verified and updated: $LATEST_PG_DUMP ($size)"
            ;;
        *)
            if [ -z "$db_path" ]; then
                case "$db_url" in
                    sqlite://*)
                        db_path="${db_url#sqlite:///}"
                        ;;
                esac
            fi

            db_path="${db_path:-bot.db}"

            case "$db_path" in
                /*) db_abs="$db_path" ;;
                *) db_abs="$PROJECT_DIR/$db_path" ;;
            esac

            if [ ! -s "$db_abs" ]; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') database not found or empty: $db_abs" >&2
                exit 1
            fi

            rm -f "$TMP_BACKUP"

            sqlite3 "$db_abs" <<SQL
.timeout 30000
.backup '$TMP_BACKUP'
SQL

            quick_check="$(sqlite3 "$TMP_BACKUP" 'PRAGMA quick_check;' | tr -d '\r')"
            if [ "$quick_check" != "ok" ]; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') backup quick_check failed: $quick_check" >&2
                rm -f "$TMP_BACKUP"
                exit 1
            fi

            if [ -f "$LATEST_BACKUP" ]; then
                cp -f "$LATEST_BACKUP" "$PREVIOUS_BACKUP"
            fi

            mv -f "$TMP_BACKUP" "$LATEST_BACKUP"
            archive_member="$(basename "$LATEST_BACKUP")"

            size="$(du -h "$LATEST_BACKUP" | awk '{print $1}')"
            echo "$(date '+%Y-%m-%d %H:%M:%S') sqlite backup updated: $LATEST_BACKUP ($size) from $db_abs"
            ;;
    esac

    rm -f "$TMP_ARCHIVE"
    tar -C "$BACKUP_DIR" -czf "$TMP_ARCHIVE" "$archive_member"
    mv -f "$TMP_ARCHIVE" "$LATEST_ARCHIVE"

    archive_size="$(du -h "$LATEST_ARCHIVE" | awk '{print $1}')"
    echo "$(date '+%Y-%m-%d %H:%M:%S') archive updated: $LATEST_ARCHIVE ($archive_size)"

    if [ "${SEND_BACKUP_TO_ADMINS:-1}" = "1" ]; then
        send_archive_to_admins "$LATEST_ARCHIVE" "$archive_name" "$created_at"
        echo "$(date '+%Y-%m-%d %H:%M:%S') archive sent to admins"
    fi
) 9>"$LOCK_FILE"
