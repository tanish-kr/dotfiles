if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

bindkey -v
# bindkey -e
autoload -U compinit; compinit
setopt auto_pushd
setopt pushd_ignore_dups
setopt extended_glob
setopt hist_ignore_all_dups
setopt hist_ignore_space

# zshプロンプトにモード表示####################################
function zle-line-init zle-keymap-select {
  case $KEYMAP in
    vicmd)
    PROMPT="%{$fg[red]%}[%{$reset_color%}%n/%{$fg_bold[red]%}NOR%{$reset_color%}%{$fg[red]%}]%#%{$reset_color%} "
    ;;
    main|viins)
    PROMPT="%{$fg[red]%}[%{$reset_color%}%n/%{$fg_bold[cyan]%}INS%{$reset_color%}%{$fg[red]%}]%#%{$reset_color%} "
    ;;
  esac
  zle reset-prompt
}
zle -N zle-line-init
zle -N zle-keymap-select
