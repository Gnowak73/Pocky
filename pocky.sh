#!/usr/bin/env bash
# usage: chmod +x pocky.sh && ./pocky.sh

POCKY_VERSION="0.1"
CONFIG_FILE=".vars.env"
script_dir="$(dirname "$(readlink -f "$0")")"
logo_file="$script_dir/logo.txt"

WAVE=""       # Wavelength Range
START=""      # Start date  (YYYY-MM-DD)
END=""        # End date    (YYYY-MM-DD)
SOURCE=""     # Data provider
INSTR=""      # Instrument

source "$CONFIG_FILE"


state_summary() {
  echo                      # one blank line after the logo
  printf "  Wavelength : %s\n" "${WAVE:-<unset>}"
  printf "  Date start : %s\n" "${START:-<unset>}"
  printf "  Date end   : %s\n" "${END:-<unset>}"
  printf "  Data src   : %s\n" "${SOURCE:-<unset>}"
  printf "  Instrument : %s\n" "${INSTR:-<unset>}"
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
                      --header "Select AIA wavelength channels") || return

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
  gum style --foreground 9 --bold "$1"
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
    _pause "Start date is AFTER End date -– clearing both"
    START=""; END=""
    edit_dates
  fi
}

export_vars() {
  clear

  #use temp file for atomic process (safety in case of crashes)
  tmpfile=$(mktemp)
{
    printf 'WAVE="%s"\n' "$WAVE"
    printf 'START="%s"\n' "$START"
    printf 'END="%s"\n' "$END"
    printf 'SOURCE="%s"\n' "$SOURCE"
    printf 'INSTR="%s"\n' "$INSTR"
} > "$tmpfile"

  mv "$tmpfile" "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"

}





main_menu() {
  while true; do
    show_ascii_art
    state_summary
    echo
    local menu=("Edit Wavelength" "Edit Date Range" \
                "Pick Data Source" "Pick Instrument" \
                "Export & Quit" "Quit")
    local choice
    choice=$(printf "%s\n" "${menu[@]}" | gum choose --header "POCKY") || exit 0
    case "$choice" in
      "Edit Wavelength") edit_wavelength ;;
      "Edit Date Range") edit_dates ;;
      "Pick Data Source") choose_source ;;
      "Pick Instrument")  choose_instr ;;
      "Export & Quit")    export_vars; exit 0 ;;
      "Quit") clear; exit 0 ;;
    esac
  done
}



main_menu

