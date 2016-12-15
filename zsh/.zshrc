if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

# PATHの順番に気をつけないと行けないのでこちらに設定
PATH=$HOME/bin:$PATH

# anyenvがあればそれだけでいい
if [ -e $HOME/.anyenv ]; then
  export PATH="$HOME/.anyenv/bin:$PATH"
  eval "$(anyenv init -)"
else
  if [ -e $HOME/.rbenv ]; then
    export PATH="$HOME/.rbenv/bin:$PATH"
    eval "$(rbenv init -)"
  fi
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
autoload -U colors && colors
function zle-line-init zle-keymap-select {
  case $KEYMAP in
    vicmd)
    # PROMPT="%{$fg[red]%}[%{$reset_color%}%n@%m/%{$fg_bold[red]%}%c%{$reset_color%}%{$fg[red]%}]\$%{$reset_color%} "
    PROMPT="[%{$fg[magenta]%}%n%{$reset_color%}@%{$fg[cyan]%}%m/%c%{$reset_color%}]%# "
    ;;
    main|viins)
    # PROMPT="%{$fg[red]%}[%{$reset_color%}%n@%m/%{$fg_bold[cyan]%}%c%{$reset_color%}%{$fg[red]%}]%#%{$reset_color%} "
    PROMPT="[%{$fg[green]%}%n%{$reset_color%}@%{$fg[cyan]%}%m/%c%{$reset_color%}]%# "
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

#allow tab completion in the middle of a word
setopt COMPLETE_IN_WORD

export LSCOLORS=exfxcxdxbxegedabagacad
export LS_COLORS='di=34:ln=35:so=32:pi=33:ex=31:bd=46;34:cd=43;34:su=41;30:sg=46;30:tw=42;30:ow=43;30'

# alias ls="ls -GF"
alias ls="ls -F --color"
alias gls="gls --color"

zstyle ':completion:*' list-colors 'di=34' 'ln=35' 'so=32' 'ex=31' 'bd=46;34' 'cd=43;34'

# zhs history setting
setopt APPEND_HISTORY
export HISTFILE=${HOME}/.zsh_history
export HISTSIZE=1000
export SAVEHIST=100000
setopt hist_ignore_dups
setopt EXTENDED_HISTORY
## for sharing history between zsh processes
setopt INC_APPEND_HISTORY
setopt SHARE_HISTORY

function history-all { history -E 1 }

agent="$HOME/.ssh/ssh_auth_sock"
if [ -S "$SSH_AUTH_SOCK" ]; then
    case $SSH_AUTH_SOCK in
    /tmp/*/agent.[0-9]*)
        # ln -snf "$SSH_AUTH_SOCK" $agent && export SSH_AUTH_SOCK=$agent
        export SSH_AUTH_SOCK=$agent
    esac
elif [ -S $agent ]; then
    export SSH_AUTH_SOCK=$agent
else
    echo "no ssh-agent"
fi

# if [ -n "${TMUX}" ]; then
#   # 既存のシェルの SSH_AUTH_SOCK を更新
#   function update_ssh_auth_sock() {
#     NEWVAL=`tmux show-environment | grep "^SSH_AUTH_SOCK" | cut -d"=" -f2`
#     if [ -n "${NEWVAL}" ]; then
#       SSH_AUTH_SOCK=${NEWVAL}
#     fi
#   }
#
#   # widget 化する
#   zle -N update_ssh_auth_sock
#
#   # ショートカットキー割り当て
#   bindkey "^[s" update_ssh_auth_sock
# fi
