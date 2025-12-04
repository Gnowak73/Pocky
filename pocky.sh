#!/usr/bin/env bash
# usage: chmod +x pocky.sh && ./pocky.sh

POCKY_VERSION="0.2"
CONFIG_FILE=".vars.env"
script_dir="$(dirname "$(readlink -f "$0")")"
logo_file="$script_dir/logo.txt"

WAVE=""       # Wavelength Range
START=""      # Start date  (YYYY-MM-DD)
END=""        # End date    (YYYY-MM-DD)
SOURCE="AIA"     # Data provider
FLARE_CLASS="" # Flare GOES class
COMPARATOR="" # Flare comparator
DL_EMAIL=""   # Cached download email

source "$CONFIG_FILE"

_cmp_ascii() {
  case "$COMPARATOR" in
    "≥") echo ">=" ;;
    "≤") echo "<=" ;;
    "ALL"|"All") echo "All" ;;
    *) echo "$COMPARATOR" ;;
  esac
}

_wavelength_display() {
  [[ -z $WAVE ]] && { echo "<unset>"; return; }

  # Canonical order for grouping adjacent selections
  local -a order=("94" "131" "171" "193" "211" "304" "335" "1600" "1700" "4500")
  declare -A idx
  for i in "${!order[@]}"; do idx["${order[$i]}"]=$i; done

  local IFS=','
  local -a selected
  read -ra selected <<< "$WAVE"

  # Filter to known wavelengths and drop empties
  local -a valid=()
  for w in "${selected[@]}"; do
    w=${w//[[:space:]]/}
    [[ -n ${idx[$w]+x} ]] && valid+=("$w")
  done

  (( ${#valid[@]} )) || { echo "$WAVE"; return; }

  # Sort by canonical order
  local IFS=$'\n'
  local -a sorted
  read -r -d '' -a sorted < <(
    for w in "${valid[@]}"; do echo "${idx[$w]}:$w"; done | sort -n | cut -d: -f2
    printf '\0'
  )

  # Collapse consecutive selections into ranges
  local -a out
  local start="" prev="" prev_i=""
  for w in "${sorted[@]}"; do
    local i=${idx[$w]}
    if [[ -z $start ]]; then
      start=$w; prev=$w; prev_i=$i; continue
    fi
    if (( i == prev_i + 1 )); then
      prev=$w; prev_i=$i; continue
    fi
    if [[ $start == $prev ]]; then out+=("$start"); else out+=("$start-$prev"); fi
    start=$w; prev=$w; prev_i=$i
  done

  # Flush last range
  if [[ -n $start ]]; then
    if [[ $start == $prev ]]; then out+=("$start"); else out+=("$start-$prev"); fi
  fi

  local IFS=','; echo "${out[*]}"
}


state_summary() {
#  echo                      # one blank line after the logo
#  printf "  Wavelength : %s\n" "$(_wavelength_display)"
#  printf "  Date Start : %s\n" "${START:-<unset>}"
#  printf "  Date End   : %s\n" "${END:-<unset>}"
#  printf "  Data Source   : %s\n" "${SOURCE:-<unset>}"
#  printf "  Flare Class : %s\n" "${FLARE_CLASS:-<unset>}"
#  printf "  Comparator : %s\n" "${COMPARATOR:-<unset>}"
#  printf "  Last Email  : %s\n" "${DL_EMAIL:-<unset>}"
#

#  echo                      # one blank line after the logo
  gum style --border=rounded --padding "1 1" --border-foreground=12 --align=left <<EOF
Wavelength : $(_wavelength_display)
Date Start : ${START:-<unset>}
Date End   : ${END:-<unset>}
Data Source: ${SOURCE:-<unset>}
Flare Class: ${FLARE_CLASS:-<unset>}
Comparator : ${COMPARATOR:-<unset>}
Last Email : ${DL_EMAIL:-<unset>}
EOF

}

show_ascii_art() {
  clear
  if [[ -f "$logo_file" && $(command -v tte) ]]; then
    tte -i "$logo_file" --frame-rate 640 expand --final-gradient-stops 443066 FF8855 FF6B81 FF4FAD D147FF 8B5EDB
  elif [[ -f "$logo_file" ]]; then
    cat "$logo_file"
  else
    echo "(logo missing: $logo_file)"
  fi
  printf "%80s\n" "VERSION: $POCKY_VERSION"   # right-align the version
}

edit_wavelength() {
  show_ascii_art

  local -a choices=(
    "  94 Å  | Fe XVIII (hot flares)"
    " 131 Å  | Fe VIII / Fe XXI"
    " 171 Å  | Fe IX    (quiet corona)"
    " 193 Å  | Fe XII / Fe XXIV"
    " 211 Å  | Fe XIV   (2 MK loops)"
    " 304 Å  | He II    (chromosphere)"
    " 335 Å  | Fe XVI   (2.5 MK)"
    "1600 Å  | C IV / continuum"
    "1700 Å  | continuum (photo.)"
    "4500 Å  | white-light"
  )

  # Exit status is non-zero on Esc / Ctrl-C --> we leave WAVE unchanged.
  local picked
  picked=$(printf '%s\n' "${choices[@]}" |
           gum choose --no-limit --height 12 \
                      --header $'Select AIA wavelength channels\n') || return

  # Extract just the wavelength numbers and join them with commas.
  if [[ -n $picked ]]; then
    WAVE=$(echo "$picked" | awk '{print $1}' | paste -sd, -)
  fi
}

_valid_iso_date() {          # “YYYY-MM-DD” sanity check
  [[ $1 =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1        # regex shape
  date -d "$1" +%F >/dev/null 2>&1 || return 1               # real calendar?
}

_pause() {   # message, then wait for one key
  local msg="$1"
  local color="$2"
  if [[ -n $color ]]; then
    gum style --foreground "$color" --bold "$msg"
  else
    gum style --bold "$msg"
  fi
  gum input --width 1 --placeholder="⏎" --header="(press Enter)" >/dev/null
}

edit_dates() {
  show_ascii_art
  local tmp_start tmp_end

  # get inputs
  while true; do
    tmp_start=$(gum input --placeholder="${START:-YYYY-MM-DD}" \
                          --header="Start date  (YYYY-MM-DD)  —-  leave blank to remain same")
    if [[ -z $tmp_start ]]; then
      tmp_start="$START"    # keep previous if blank
    fi
    _valid_iso_date "$tmp_start" && { START=$tmp_start; break; }
    gum style --bold --foreground 9 "Invalid date -— try again"
  done

  while true; do
    tmp_end=$(gum input --placeholder="${END:-YYYY-MM-DD}" \
                        --header="End date    (YYYY-MM-DD)  —-  leave blank to remain same")
    if [[ -z $tmp_end ]]; then
      tmp_end="$END"    # keep previous if blank
    fi
    _valid_iso_date "$tmp_end" && { END=$tmp_end; break; }
    gum style --bold --foreground 9 "Invalid date -— try again"
  done

  # make sure chronologically consistent
  if [[ -n $START && -n $END ]] &&
     (( $(date -d "$START" +%s) > $(date -d "$END" +%s) )); then
    _pause "Start date is AFTER End date -– clearing both" 9
    START=""; END=""
    edit_dates
  fi
}

export_vars() {
  #use temp file for atomic process (safety in case of crashes)
  tmpfile=$(mktemp)
{
    printf 'WAVE="%s"\n' "$WAVE"
    printf 'START="%s"\n' "$START"
    printf 'END="%s"\n' "$END"
    printf 'SOURCE="%s"\n' "$SOURCE"
    printf 'FLARE_CLASS="%s"\n' "$FLARE_CLASS"
    printf 'COMPARATOR="%s"\n' "$COMPARATOR"
    printf 'DL_EMAIL="%s"\n' "$DL_EMAIL"
} > "$tmpfile"

  mv "$tmpfile" "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"

}

flare_filter() {
  show_ascii_art
  local status op letter mag

  # get comparator
  local -a comparator_display=('>' '≥' '==' '≤' '<' 'All')
  declare -A comparator_map=(
    [">"]=">"
    ["≥"]=">="
    ["=="]="=="
    ["≤"]="<="
    ["<"]="<"
    ["All"]="All"
  )

  op=$(printf '%s\n' "${comparator_display[@]}" |
       gum choose --cursor="▶ " --header=$'Choose Comparator\n')
  status=$?                                     # Gum exit status
  [[ $status -ne 0 ]] && return                 # Esc goes back to menu
  op="${comparator_map[$op]}"
  [[ -z $op ]] && return                        # safety fallback

  if [[ $op == "All" ]]; then                   # clear filter
    COMPARATOR="All"; FLARE_CLASS="Any"; return
  fi

  # get GOES class letter
  letter=$(printf '%s\n' A B C M X |
           gum choose --cursor="▶ " --header=$'Flare GOES Class\n')
  status=$?
  [[ $status -ne 0 ]] && return

  # get flare magnitude
  local -a mags=()
  for i in {0..9}; do for t in {0..9}; do mags+=("$i.$t"); done; done

  mag=$(printf '%s\n' "${mags[@]}" |
        gum choose --cursor="▶ " --height 10 \
                   --header=$'Numeric Multiplier\n')
  status=$?
  [[ $status -ne 0 ]] && return

  # save
  COMPARATOR="$op"
  FLARE_CLASS="${letter}${mag}"
}

select_flares() {
  show_ascii_art

  if [[ -z $START || -z $END ]]; then
    gum style --foreground 9 --bold "Set a date range first."
    _pause "Returning to menu"; return
  fi
  if [[ -z $WAVE ]]; then
    gum style --foreground 9 --bold "Select at least one wavelength first."
    _pause "Returning to menu"; return
  fi

  local cmp_ascii
  cmp_ascii=$(_cmp_ascii)
  local flare_class="${FLARE_CLASS:-A0.0}"
  [[ -z $cmp_ascii ]] && { gum style --foreground 9 --bold "Set a comparator first."; _pause "Returning to menu"; return; }

  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/pocky_flares.XXXXXXXX.tsv")"

  if ! python query.py "$START" "$END" "$cmp_ascii" "$flare_class" "$WAVE" "$tmp"; then
    gum style --foreground 9 --bold "Flare listing failed"
    rm -f "$tmp"
    _pause "Returning to menu"; return
  fi

  local header selection
  header=$(head -n1 "$tmp")

  # Prepare display lines without wavelength, keeping order to recover full rows
  mapfile -t rows < <(tail -n +2 "$tmp")
  if ((${#rows[@]}==0)); then
    gum style --foreground 10 "No flares found."
    rm -f "$tmp"
    _pause "Returning to menu"; return
  fi

  mapfile -t choices < <(
    printf '%s\n' "${rows[@]}" | awk -F'\t' '{printf "%s\t%s\t%s\n", $1, $5, $3}'
  )

  selection=$(
    printf '%s\n' "${choices[@]}" \
    | gum choose --no-limit --height 20 --header "Choose Flares to Catalogue"
  ) || selection=""
  rm -f "$tmp"

  [[ -z $selection ]] && { gum style --foreground 10 "No flares selected."; _pause "Returning to menu"; return; }

  local perm_dir perm_file
  perm_dir="$script_dir"
  perm_file="$perm_dir/flare_cache.tsv"
  mkdir -p "$perm_dir"
  local -a new_rows=()
  while IFS= read -r line; do
    for i in "${!choices[@]}"; do
      if [[ ${choices[$i]} == "$line" ]]; then
        new_rows+=("${rows[$i]}")
        break
      fi
    done
  done <<< "$selection"

  local tmp_out
  tmp_out="$(mktemp "$perm_dir/flare_cache.XXXXXX")"
  printf '%s\n' "$header" > "$tmp_out"
  {
    if [[ -f "$perm_file" ]]; then
      tail -n +2 "$perm_file"
    fi
    printf '%s\n' "${new_rows[@]}"
  } | awk '!seen[$0]++' >> "$tmp_out"
  mv "$tmp_out" "$perm_file"
  gum style --foreground 10 "Saved picks → $perm_file"
  _pause "Done"
}

clear_flare_cache() {
  show_ascii_art
  local file="$script_dir/flare_cache.tsv"
  if [[ ! -f $file ]]; then
    gum style --bold "No flare cache found at $file"
    _pause "Returning to menu"
    return
  fi

  if ! gum confirm --default=false "Clear all flare entries in $file?"; then
    _pause "Canceled"
    return
  fi

  # Preserve header when clearing; fall back to current schema if missing
  local header
  if [[ -s $file ]]; then
    header=$(head -n1 "$file")
  fi
  header=${header:-$'description\tflare_class\tstart\tend\tcoordinates\twavelength'}

  printf '%s\n' "$header" > "$file"
  gum style --foreground 10 "Cleared flare cache contents (header kept)."
  _pause "Done"
}

delete_flare_rows() {
  show_ascii_art
  local file="$script_dir/flare_cache.tsv"
  if [[ ! -s $file ]]; then
    gum style --bold "Cache is empty (no flare_cache.tsv found or no data)."
    _pause "Returning to menu"
    return
  fi

  local header
  header=$(head -n1 "$file")
  mapfile -t rows < <(tail -n +2 "$file")
  if ((${#rows[@]}==0)); then
    gum style --bold "Cache has header only (no rows)."
    _pause "Returning to menu"
    return
  fi

  # Show description + coordinates for selection; keep mapping to full rows
  mapfile -t choices < <(
    printf '%s\n' "${rows[@]}" | awk -F'\t' '{printf "%s\t%s\n", $1, $5}'
  )

  local selection
  selection=$(
    printf '%s\n' "${choices[@]}" \
    | gum filter --no-limit --height 20 --header "Select cache rows to delete" --fuzzy
  ) || selection=""

  [[ -z $selection ]] && { gum style --foreground 10 "No rows selected."; _pause "Returning to menu"; return; }

  # Mark selected indices
  declare -A delete_idx=()
  while IFS= read -r line; do
    for i in "${!choices[@]}"; do
      if [[ ${choices[$i]} == "$line" ]]; then
        delete_idx[$i]=1
        break
      fi
    done
  done <<< "$selection"

  local tmp
  tmp="$(mktemp "$script_dir/flare_cache.XXXXXX")"
  printf '%s\n' "$header" > "$tmp"
  for i in "${!rows[@]}"; do
    [[ ${delete_idx[$i]+x} ]] && continue
    printf '%s\n' "${rows[$i]}" >> "$tmp"
  done
  mv "$tmp" "$file"
  gum style --foreground 10 "Removed selected rows."
  _pause "Done"
}

view_flare_cache() {
  show_ascii_art
  local file="$script_dir/flare_cache.tsv"
  if [[ ! -s $file ]]; then
    gum style --bold "Cache is empty (no flare_cache.tsv found or no data)."
    _pause "Returning to menu"
    return
  fi
  gum pager < "$file"
}

cache_menu() {
  while true; do
    show_ascii_art
    local opts=("View Cache" "Delete Rows" "Clear Cache" "Back")
    local choice
    choice=$(printf '%s\n' "${opts[@]}" | gum choose --header=$'\n') || return
    case "$choice" in
      "View Cache") view_flare_cache ;;
      "Delete Rows") delete_flare_rows ;;
      "Clear Cache") clear_flare_cache ;;
      "Back") return ;;
    esac
  done
}

_prompt_dl_args_jsoc() {
  local def_out="${1}"
  local def_email="${DL_EMAIL:-${JSOC_EMAIL:-}}"
  local def_tsv="$script_dir/flare_cache.tsv"
  local def_conn="6"
  local def_splits="3"
  local def_attempts="5"
  local def_cadence="12s"
  local def_before="0"
  local def_after=""   # blank means default to flare duration

  local email tsv outdir max_conn max_splits attempts cadence pad_before pad_after
  email=$(gum input --header="JSOC Email (env JSOC_EMAIL used if blank)" --value="$def_email") || return 1
  tsv=$(gum input --header="Path to flare cache TSV" --value="$def_tsv") || return 1
  outdir=$(gum input --header="Output directory" --value="$def_out") || return 1
  max_conn=$(gum input --header="Downloader max connections" --value="$def_conn") || return 1
  max_splits=$(gum input --header="Downloader max splits" --value="$def_splits") || return 1
  attempts=$(gum input --header="Max attempts per window/wavelength" --value="$def_attempts") || return 1
  cadence=$(gum input --header="Cadence (e.g., 12s)" --value="$def_cadence") || return 1
  pad_before=$(gum input --header="Minutes before event start" --value="$def_before") || return 1
  pad_after=$(gum input --header="Minutes after event start (blank = to event end)" --value="$def_after") || return 1

  printf '%s\n' "$email" "$tsv" "$outdir" "$max_conn" "$max_splits" "$attempts" "$cadence" "$pad_before" "$pad_after"
}

run_jsoc_download() {
  show_ascii_art
  if [[ ! -f "$script_dir/flare_cache.tsv" ]]; then
    gum style --foreground 9 --bold "flare_cache.tsv not found in $script_dir"
    _pause "Returning to menu"; return
  fi

  if ! IFS=$'\n' read -r email tsv outdir max_conn max_splits attempts cadence pad_before pad_after < <(_prompt_dl_args_jsoc "$script_dir/data_aia_lvl1"); then
    _pause "Returning to menu"; return
  fi

  # Fallbacks when user leaves entries blank
  email=$(echo "$email" | xargs)
  email=${email:-$JSOC_EMAIL}
  DL_EMAIL="$email"
  export_vars
  tsv=${tsv:-$script_dir/flare_cache.tsv}
  outdir=${outdir:-$script_dir/data_aia_lvl1}
  max_conn=${max_conn:-6}
  max_splits=${max_splits:-3}
  attempts=${attempts:-5}
  cadence=${cadence:-12s}
  series="aia.lev1_euv_12s"
  pad_before=${pad_before:-0}
  pad_after=${pad_after:-}

  if [[ -z $email ]]; then
    gum style --foreground 9 --bold "JSOC email is required (set JSOC_EMAIL or enter it)."
    _pause "Returning to menu"; return
  fi

  local cmd=(python fetch_jsoc_drms.py
    --tsv "$tsv"
    --out "$outdir"
    --max-conn "$max_conn"
    --max-splits "$max_splits"
    --attempts "$attempts"
    --cadence "$cadence"
    --series "$series"
    --pad-before "$pad_before"
  )
  [[ -n $pad_after ]] && cmd+=(--pad-after "$pad_after")
  cmd+=(--email "$email")

  if ! gum confirm --default=true "Proceed with download?"; then
    _pause "Canceled"; return
  fi

  gum style --foreground 14 "Running: ${cmd[*]}"
  if "${cmd[@]}"; then
    gum style --foreground 10 "Download finished."
  else
    gum style --foreground 9 --bold "Download failed."
  fi
  _pause "Done"
}

run_jsoc_download_lvl15() {
  show_ascii_art
  if [[ ! -f "$script_dir/flare_cache.tsv" ]]; then
    gum style --foreground 9 --bold "flare_cache.tsv not found in $script_dir"
    _pause "Returning to menu"; return
  fi

  if ! IFS=$'\n' read -r email tsv outdir max_conn max_splits attempts cadence pad_before pad_after < <(_prompt_dl_args_jsoc "$script_dir/data_aia_lvl1.5"); then
    _pause "Returning to menu"; return
  fi

  # Fallbacks when user leaves entries blank
  email=$(echo "$email" | xargs)
  email=${email:-$JSOC_EMAIL}
  DL_EMAIL="$email"
  export_vars
  tsv=${tsv:-$script_dir/flare_cache.tsv}
  outdir=${outdir:-$script_dir/data_aia_lvl1.5}
  max_conn=${max_conn:-6}
  max_splits=${max_splits:-3}
  attempts=${attempts:-5}
  cadence=${cadence:-12s}
  series="aia.lev1_euv_12s"
  pad_before=${pad_before:-0}
  pad_after=${pad_after:-}

  if [[ -z $email ]]; then
    gum style --foreground 9 --bold "JSOC email is required (set JSOC_EMAIL or enter it)."
    _pause "Returning to menu"; return
  fi

  local cmd=(python fetch_jsoc_drms.py
    --tsv "$tsv"
    --out "$outdir"
    --max-conn "$max_conn"
    --max-splits "$max_splits"
    --attempts "$attempts"
    --cadence "$cadence"
    --series "$series"
    --pad-before "$pad_before"
    --aia-scale
    --email "$email"
  )
  [[ -n $pad_after ]] && cmd+=(--pad-after "$pad_after")

  if ! gum confirm --default=true "Proceed with download?"; then
    _pause "Canceled"; return
  fi

  gum style --foreground 14 "Running: ${cmd[*]}"
  if "${cmd[@]}"; then
    gum style --foreground 10 "Download finished."
  else
    gum style --foreground 9 --bold "Download failed."
  fi
  _pause "Done"
}

run_jsoc_fido_lvl1() {
  show_ascii_art
  if [[ ! -f "$script_dir/flare_cache.tsv" ]]; then
    gum style --foreground 9 --bold "flare_cache.tsv not found in $script_dir"
    _pause "Returning to menu"; return
  fi

  local provider
  provider=$(printf '%s\n' "JSOC" "VSO" | gum choose --header="Select Fido provider" --cursor="▶ ") || { _pause "Returning to menu"; return; }
  provider=$(echo "$provider" | tr '[:upper:]' '[:lower:]')

  # Prompt core args; email only needed for JSOC
  local def_tsv="$script_dir/flare_cache.tsv"
  local def_out="$script_dir/data_aia_lvl1"
  local def_conn="6" def_splits="3" def_attempts="3" def_cadence="12" def_before="0" def_after=""
  local email tsv outdir max_conn max_splits attempts cadence pad_before pad_after
  if [[ $provider == "jsoc" ]]; then
    local def_email="${DL_EMAIL:-${JSOC_EMAIL:-}}"
    email=$(gum input --header="JSOC Email (env JSOC_EMAIL used if blank)" --value="$def_email") || { _pause "Returning to menu"; return; }
  fi
  tsv=$(gum input --header="Path to flare cache TSV" --value="$def_tsv") || { _pause "Returning to menu"; return; }
  outdir=$(gum input --header="Output directory" --value="$def_out") || { _pause "Returning to menu"; return; }
  max_conn=$(gum input --header="Downloader max connections" --value="$def_conn") || { _pause "Returning to menu"; return; }
  max_splits=$(gum input --header="Downloader max splits" --value="$def_splits") || { _pause "Returning to menu"; return; }
  attempts=$(gum input --header="Fetch attempts per event" --value="$def_attempts") || { _pause "Returning to menu"; return; }
  cadence=$(gum input --header="Cadence (seconds)" --value="$def_cadence") || { _pause "Returning to menu"; return; }
  pad_before=$(gum input --header="Minutes before event start" --value="$def_before") || { _pause "Returning to menu"; return; }
  pad_after=$(gum input --header="Minutes after event start (blank = to event end)" --value="$def_after") || { _pause "Returning to menu"; return; }

  # Fallbacks when user leaves entries blank
  email=$(echo "${email:-}" | xargs)
  tsv=${tsv:-$script_dir/flare_cache.tsv}
  outdir=${outdir:-$script_dir/data_aia_lvl1}
  cadence=${cadence:-12}
  pad_before=${pad_before:-0}
  pad_after=${pad_after:-}

  if [[ $provider == "jsoc" && -z $email ]]; then
    gum style --foreground 9 --bold "JSOC email is required (set JSOC_EMAIL or enter it)."
    _pause "Returning to menu"; return
  fi

  local cmd=(python fetch_fido.py
    --tsv "$tsv"
    --out "$outdir"
    --cadence "${cadence:-12}"
    --pad-before "${pad_before:-0}"
    --max-conn "${max_conn:-6}"
    --max-splits "${max_splits:-3}"
    --attempts "${attempts:-3}"
    --provider "$provider"
  )
  if [[ $provider == "jsoc" ]]; then
    cmd+=(--email "$email")
    DL_EMAIL="$email"
    export_vars
  fi
  [[ -n $pad_after ]] && cmd+=(--pad-after "$pad_after")

  if ! gum confirm --default=true "Proceed with download?"; then
    _pause "Canceled"; return
  fi

  gum style --foreground 14 "Running: ${cmd[*]}"
  if "${cmd[@]}"; then
    gum style --foreground 10 "Download finished."
  else
    gum style --foreground 9 --bold "Download failed."
  fi
  _pause "Done"
}

run_jsoc_fido_lvl15() {
  show_ascii_art
  if [[ ! -f "$script_dir/flare_cache.tsv" ]]; then
    gum style --foreground 9 --bold "flare_cache.tsv not found in $script_dir"
    _pause "Returning to menu"; return
  fi

  if ! IFS=$'\n' read -r email tsv outdir max_conn max_splits attempts cadence pad_before pad_after < <(_prompt_dl_args_jsoc "$script_dir/data_aia_lvl1.5"); then
    _pause "Returning to menu"; return
  fi

  # Fallbacks when user leaves entries blank
  email=$(echo "$email" | xargs)
  email=${email:-$JSOC_EMAIL}
  DL_EMAIL="$email"
  export_vars
  tsv=${tsv:-$script_dir/flare_cache.tsv}
  outdir=${outdir:-$script_dir/data_aia_lvl1.5}
  cadence=${cadence:-12}
  pad_before=${pad_before:-0}
  pad_after=${pad_after:-}

  if [[ -z $email ]]; then
    gum style --foreground 9 --bold "JSOC email is required (set JSOC_EMAIL or enter it)."
    _pause "Returning to menu"; return
  fi

  gum style --foreground 9 --bold "Fido level 1.5 is not supported (use JSOC DRMS Lvl 1.5)."
  _pause "Returning to menu"; return
}

download_menu() {
  while true; do
    show_ascii_art
    local opts=(
      "JSOC DRMS Lvl 1 Client"
      "JSOC DRMS Lvl 1.5 Client"
      "---"
      "Fido Fetch Lvl 1"
      "---"
      "Back"
    )
    local choice
    choice=$(printf '%s\n' "${opts[@]}" | gum choose --header=$'\n') || return
    case "$choice" in
      "JSOC DRMS Lvl 1 Client") run_jsoc_download ;;
      "JSOC DRMS Lvl 1.5 Client") run_jsoc_download_lvl15 ;;
      "Fido Fetch Lvl 1") run_jsoc_fido_lvl1 ;;
      "Back") return ;;
      "---") continue ;;
    esac
  done
}

main_menu() {
  while true; do
    show_ascii_art
    export_vars
    state_summary
    echo
    local menu=("Edit Wavelength" "Edit Date Range" "Edit Flare Class Filter" "Select Flares" "Cache Options" "Download FITS" "Quit")
    local choice

    choice=$(printf "%s\n" "${menu[@]}" | gum choose --header=$'\n') || exit 0
    case "$choice" in
      "Edit Wavelength") edit_wavelength ;;
      "Edit Date Range") edit_dates ;;
      "Edit Flare Class Filter") flare_filter ;;
      "Select Flares") select_flares ;;
      "Cache Options") cache_menu ;;
      "Download FITS") download_menu ;;
      "Quit") clear && export_vars; exit 0 ;;
    esac
  done
}



main_menu
