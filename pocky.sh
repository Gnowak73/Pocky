#!/usr/bin/env bash
# usage: chmod +x pocky.sh && ./pocky.sh

POCKY_VERSION="0.1"
CONFIG_FILE=".vars.env"
script_dir="$(dirname "$(readlink -f "$0")")"
logo_file="$script_dir/logo.txt"

WAVE=""       # Wavelength Range
START=""      # Start date  (YYYY-MM-DD)
END=""        # End date    (YYYY-MM-DD)
SOURCE="AIA"     # Data provider
FLARE_CLASS="" # Flare GOES class
COMPARATOR="" # Flare comparator

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
  echo                      # one blank line after the logo
  printf "  Wavelength : %s\n" "$(_wavelength_display)"
  printf "  Date Start : %s\n" "${START:-<unset>}"
  printf "  Date End   : %s\n" "${END:-<unset>}"
  printf "  Data Source   : %s\n" "${SOURCE:-<unset>}"
  printf "  Flare Class : %s\n" "${FLARE_CLASS:-<unset>}"
  printf "  Comparator : %s\n" "${COMPARATOR:-<unset>}"

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
                          --header="Start date  (YYYY-MM-DD)  —-  leave blank to unset")
    [[ -z $tmp_start ]] && { START=""; break; }              # blank → unset
    _valid_iso_date "$tmp_start" && { START=$tmp_start; break; }
    gum style --bold --foreground 9 "Invalid date -— try again"
  done

  while true; do
    tmp_end=$(gum input --placeholder="${END:-YYYY-MM-DD}" \
                        --header="End date    (YYYY-MM-DD)  —-  leave blank to unset")
    [[ -z $tmp_end ]] && { END=""; break; }
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
    _pause "Returning to menu" 9; return
  fi
  if [[ -z $WAVE ]]; then
    gum style --foreground 9 --bold "Select at least one wavelength first."
    _pause "Returning to menu" 9; return
  fi

  local cmp_ascii
  cmp_ascii=$(_cmp_ascii)
  local flare_class="${FLARE_CLASS:-A0.0}"
  [[ -z $cmp_ascii ]] && { gum style --foreground 9 --bold "Set a comparator first."; _pause "Returning to menu" 9; return; }

  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/pocky_flares.XXXXXXXX.tsv")"

  if ! python query.py "$START" "$END" "$cmp_ascii" "$flare_class" "$WAVE" "$tmp"; then
    gum style --foreground 9 --bold "Flare listing failed"
    rm -f "$tmp"
    _pause "Returning to menu" 9; return
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

main_menu() {
  while true; do
    show_ascii_art
    export_vars
    state_summary
    echo
    local menu=("Edit Wavelength" "Edit Date Range" "Edit Flare Class Filter" "Select Flares" "Cache Options" "Quit")
    local choice

    choice=$(printf "%s\n" "${menu[@]}" | gum choose --header=$'\n') || exit 0
    case "$choice" in
      "Edit Wavelength") edit_wavelength ;;
      "Edit Date Range") edit_dates ;;
      "Edit Flare Class Filter") flare_filter ;;
      "Select Flares") select_flares ;;
      "Cache Options") cache_menu ;;
      "Quit") clear && export_vars; exit 0 ;;
    esac
  done
}



main_menu
