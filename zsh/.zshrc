if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

bindkey -v
# bindkey -e
bindkey "^R" history-incremental-search-backward
autoload -U compinit; compinit
setopt auto_pushd
setopt pushd_ignore_dups
setopt extended_glob
setopt hist_ignore_all_dups
setopt hist_ignore_space
setopt nonomatch
setopt interactivecomments

# zshプロンプトにモード表示####################################
function zle-line-init zle-keymap-select {
  case $KEYMAP in
    vicmd)
    PROMPT="%{$fg[red]%}[%{$reset_color%}%n@%m/%{$fg_bold[red]%}NOR%{$reset_color%}%{$fg[red]%}]%#%{$reset_color%} "
    ;;
    main|viins)
    PROMPT="%{$fg[red]%}[%{$reset_color%}%n@%m/%{$fg_bold[cyan]%}INS%{$reset_color%}%{$fg[red]%}]%#%{$reset_color%} "
    ;;
  esac
  zle reset-prompt
}
zle -N zle-line-init
zle -N zle-keymap-select

if [ -e /usr/share/terminfo/x/xterm-256color ]; then
        export TERM='xterm-256color'
else
        export TERM='xterm-color'
fi

autoload -U compinit
compinit

export LSCOLORS=exfxcxdxbxegedabagacad
export LS_COLORS='di=34:ln=35:so=32:pi=33:ex=31:bd=46;34:cd=43;34:su=41;30:sg=46;30:tw=42;30:ow=43;30'

# alias ls="ls -GF"
alias ls="ls -F --color"
alias gls="gls --color"

zstyle ':completion:*' list-colors 'di=34' 'ln=35' 'so=32' 'ex=31' 'bd=46;34' 'cd=43;34'
