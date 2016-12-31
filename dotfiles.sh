#!/bin/bash

dotfiles=$(find `pwd` -mindepth 1 -type f \
    -name "*.*" \
    -not -name "*.swp" \
    -not -name "*.swo" \
    -not -name "*.DS_Store" \
    -not -name "*.gitignore" \
    -not -name "dotfiles.sh" \
    -not -name "*.md" \
    -not -name "*.gitkeep" \
    -not -path "*.git/*")

install() {
  backup
  set
}

set() {
  for file_name in $(dotfiles); do
    ln -svf $file_name ~
    echo "Set link to ${file_name}."
  done
}

unset() {
  for file_name in $(list); do
    unlink $file_name
    echo "Set unlink to ${file_name}."
  done
}

delete() {
  for file_name in $(list); do
    rm -rf $file_name
    echo "Delete to ${file_name}."
  done
}

backup() {
  for file_name in $(list); do
    cp -RH $file_name org/
    echo "Backup to ${file_name}."
  done
}

list() {
  home_dotsfile=$(find $HOME -maxdepth 1 -type l)
  for file_name in $home_dotsfile; do
    link_path=$(readlink $file_name)
    if [ $(contains "${dotfiles[@]}" "$link_path") == "y" ]; then
      echo "$file_name"
    fi
  done
}

contains() {
  local n=$#
  local value=${!n}
  for ((i=1;i < $#;i++)) {
    if [[ "${!i}" =~ "${value}" ]]; then
      echo "y"
      return 0
    fi
  }
  echo "n"
  return 1
}

help() {
  echo "Useage: $0 <install|update|delete|backup|list|help>"
  echo "  - install|-i:     Install dotfiles."
  echo "  - update|-u:      Update dotfiles."
  echo "  - delete|-d:      Delete a dotfiles."
  echo "  - list|-l:        List dotfiles."
}

case $1 in
  install|-i)
    ;;
  update|-u)
    update
    exit 0
    ;;
  delete|-d)
    exit 0
    ;;
  backup|-b)
    backup
    exit 0
    ;;
  list|-l)
    cnt=0
    for file_name in $(list); do
      echo "$file_name -> $(readlink $file_name)"
      let cnt++
    done
    echo "Total lists $cnt"
    exit 0
    ;;
  help|-h)
    help
    exit 0
    ;;
  *)
    help
    exit 1
    ;;
esac
