#!/bin/bash

dotfiles=($(find `pwd` -mindepth 1 -maxdepth 2 -regex ".*\/\..*" \
    -not -type d \
    -not -name "*.DS_Store" \
    -not -name "*.gitignore" \
    -not -name "*.gitmodules" \
    -not -name "*.git" \
    -not -name "*.swp" \
    -not -name "*.swo" \
    -not -path "*/.git/*" \
    -not -path "*/org/*"))
dotfiles+=("$(pwd)/vim/.vim")
dotfiles+=("$(pwd)/pip/.pip")
dotfiles+=("$(pwd)/tmux/.tmux")
dotfiles+=("$(pwd)/emacs/.emacs.d")
dotfiles+=($(pwd)/bin/*)
dotfiles+=("$(pwd)/ssh/rc")
dotfiles+=("$(pwd)/nvim")
dotfiles+=("$(pwd)/vscode/*.json")

home_dotsfile=($(find $HOME -maxdepth 1 -regex ".*\/\..*" \
    -not -type d \
    -not -name "*.DS_Store" \
    -not -name "*.swp" \
    -not -name "*.swo"))
home_dotsfile+=("$HOME/.vim")
home_dotsfile+=("$HOME/.emacs.d")
home_dotsfile+=($HOME/bin/*)
home_dotsfile+=("$HOME/.ssh/rc")
home_dotsfile+=("$(pwd)/nvim")
if [ "$(uname)" == 'Darwin' ]; then
  home_dotsfile+="$HOME/Library/Application Support/Code/User/*.json"
elif [ "$(expr substr $(uname -s) 1 5)" == 'Linux']; then
  home_dotsfile+="$HOME/.config/Code/User/*.json"
fi

install() {
  backup
  git submodule update --init --recursive
  set
}

set() {
  for file_name in "${dotfiles[@]}"; do
    if [[ $file_name =~ "ssh" ]]; then
      ln -svf $file_name $HOME/.ssh
    elif [[ $file_name =~ "bin" ]]; then
      ln -svf $file_name $HOME/bin
    elif [[ $file_name =~ "nvim" ]]; then
      if [ -e $HOME/.config ]; then
        ln -svf $file_name $HOME/.config/nvim
      else
        mkdir $HOME/.config
        ln -svf $file_name $HOME/.config/nvim
      fi
    elif [[ $file_name =~ "vscode" ]]; then
      if [ "$(uname)" == 'Darwin' ]; then
        ln -svf $file_name "$HOME/Library/Application Support/Code/User"
      elif [ "$(expr substr $(uname -s) 1 5)" == 'Linux']; then
        ln -svf $file_name "$HOME/.config/Code/User"
      fi
    else
      ln -svf $file_name $HOME
    fi
    echo "Set link to ${file_name}."
  done
}

unset() {
  for file_name in $(list); do
    unlink $file_name
    echo "Unlink to ${file_name}."
  done
}

delete() {
  for file_name in $(list); do
    rm -rf $file_name
    echo "Delete to ${file_name}."
  done
}

backup() {
  for file_name in "${home_dotsfile[@]}"; do
    cp -RH $file_name org/
    echo "Backup to ${file_name}."
  done
}

list() {
  for file_name in "${home_dotsfile[@]}"; do
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

debug() {
  echo "dotfiles"
  # echo "$dotfiles"
  for file_name in "${dotfiles[@]}"; do
    echo $file_name
  done
  echo "home_dotfiles"
  # echo ${home_dotsfile[@]}
  for file_name in "${home_dotsfile[@]}"; do
    echo $file_name
  done
}

help() {
  echo "Useage: $0 <install|update|delete|backup|list|help>"
  echo "  - install|-i:     Install dotfiles."
  echo "  - set|-s:         Set dotfiles."
  echo "  - unset|-u:       Un set dotfiles."
  echo "  - delete|-d:      Delete a dotfiles."
  echo "  - list|-l:        List dotfiles."
}

case $1 in
  debug)
    debug
    exit 0
    ;;
  install|-i)
    install
    exit 0
    ;;
  set|-s)
    set
    exit 0
    ;;
  unset|-u)
    unset
    exit 0
    ;;
  delete|-d)
    delete
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
