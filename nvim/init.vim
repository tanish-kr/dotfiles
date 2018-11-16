""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" 書式設定
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

"インデント設定
set autoindent
set tabstop=2
set shiftwidth=2
set expandtab
set softtabstop=2
""自動インデント
set smarttab
"行番号
set number
"ペーストモード
" set paste

"クリップボード設定
"" ビジュアルモードで選択したテキストをクリップボードに入れる
"set clipboard+=autoselect
""yankしたテキストを*レジスタにも入れる
set clipboard+=unnamed

" 折りたたみ
set foldenable
" set foldmethod=syntax
set foldmethod=indent
let perl_fold=3
set foldlevel=100
set foldnestmax=20

augroup foldmethod-syntax
  autocmd!
  autocmd InsertEnter * if &l:foldmethod ==# 'syntax'
  \                   |   setlocal foldmethod=manual
  \                   | endif
  autocmd InsertLeave * if &l:foldmethod ==# 'manual'
  \                   |   setlocal foldmethod=syntax
  \                   | endif
augroup END
" Insert modeで自動折り畳みを行わない
autocmd InsertEnter * if !exists('w:last_fdm')
            \| let w:last_fdm=&foldmethod
            \| setlocal foldmethod=manual
            \| endif
autocmd InsertLeave,WinLeave * if exists('w:last_fdm')
            \| let &l:foldmethod=w:last_fdm
            \| unlet w:last_fdm
            \| endif


""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" 外観設定
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

"現在のモード表示
set showmode
"ウィンドウのタイトルを変更
set title
"終了時にターミナルのタイトルを戻す
let &t_ti .= "\e[22;0t"
let &t_te .= "\e[23;0t"
"閉括弧に対応する括弧の強調表示
set showmatch
"タブ文字、空白文字、改行文字設定
set list
if has("mac")
  " mac では段落記号が全角でしか認識しないため
  set listchars=tab:»-,trail:.,eol:↲,extends:»,precedes:«,nbsp:%
elseif has("unix")
  set listchars=tab:»-,trail:.,eol:¶,extends:»,precedes:«,nbsp:%
endif
"全角スペースの表示
function! ZenkakuSpace()
   highlight ZenkakuSpace cterm=reverse ctermfg=DarkGray gui=reverse guifg=DarkGray
endfunction
if has('syntax')
   augroup ZenkakuSpace
       autocmd!
       autocmd ColorScheme * call ZenkakuSpace()
       autocmd VimEnter,WinEnter * match ZenkakuSpace /　/
   augroup END
   call ZenkakuSpace()
endif
" カーソル行可視化
set cursorline
"行の折り返し
set wrap
"カーソル位置表示
set ruler

"カラーテーマ
" set term=builtin_linux
" set ttytype=builtin_linux
set t_Co=256
if &term=="xterm"
     set t_Co=8
     set t_Sb=[4%dm
     set t_Sf=[3%dm
endif

set background=dark
autocmd ColorScheme * highlight Visual term=reverse cterm=reverse ctermfg=230 ctermbg=238 gui=reverse guifg=#ffffd7 guibg=#444444
autocmd ColorScheme  * highlight LineNr term=underline ctermfg=195 ctermbg=242 guifg=#d7ffff guibg=#666666
" autocmd ColorScheme  * highlight SpellBad term=reverse ctermbg=5 gui=undercurl guisp=#800080
" autocmd ColorScheme  * highlight CursorLine term=underline ctermbg=234 guibg=#293739
" autocmd ColorScheme  * highlight Comment term=bold ctermfg=59 guifg=#5f5f5f
colorscheme atom_dark
"colorscheme Tomorrow-Night-Bright
"colorscheme molokai
" let g:molokai_original = 1
" let g:rehash256 = 1

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" 検索設定
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

"" 検索結果をハイライト
set hlsearch
"" 末尾から再び検索
set wrapscan
"" 大文字と小文字を区別しない
set noignorecase

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
"  ファイル関連
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

"バックアップファイル非作成
set nobackup
set noundofile
"エンコーディング
set fileencoding=utf-8
"改行コードをunixで保存
set fileformat=unix
" スペルチェック
set spell
if has("mac")
  set spelllang=en,cjk
endif
"ファイルブラウザで使用するディレクトリの場所
set browsedir=buffer

" ruby 速度改善
" let g:ruby_path="~/.rbenv/versions/2.3.1/bin/ruby"
au BufNewFile, BufRead *.rb let g:ruby_path=system('rbenv prefix')

"""  Explore
let g:netrw_liststyle = 3
" バナー削除
let g:netrw_banner = 0
" 縦に開いておく
let g:netrw_browse_split = 4
let g:netrw_altv = 1
" 幅
let g:netrw_winsize = 15
" Project Drawer
augroup ProjectDrawer
  autocmd!
  autocmd VimEnter * :Vexplore
augroup END
"augroup VimStartup
"  au!
"  au VimEnter * if expand("%") == "" | e . | endif
"augroup END
" create newfileで新規bufferに開く
autocmd filetype netrw call Netrw_mappings()
function! Netrw_mappings()
  "noremap <buffer>% :call CreateInPreview()<cr>
  noremap <buffer>n :call CreateInPreview()<cr>
endfunction
function! CreateInPreview()
  let l:filename = input("please enter filename: ")
  "execute 'pedit ' . b:netrw_curdir.'/'.l:filename
  execute 'tabe' . b:netrw_curdir.'/'.l:filename
endfunction

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" キーマッピング
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

" ハイライトをEscでクリア
nnoremap <ESC><ESC> :nohlsearch<CR>

" vimgrep
nnoremap // :vimgrep
nnoremap [q :cprevious<CR>   " 前へ
nnoremap ]q :cnext<CR>       " 次へ
nnoremap [Q :<C-u>cfirst<CR> " 最初へ
nnoremap ]Q :<C-u>clast<CR>  " 最後へ

" 括弧自動挿入, 位置調整
inoremap { {}<Left>
inoremap {<Enter> {}<Left><CR><ESC><S-o>
inoremap [ []<Left>
inoremap [<Enter> []<Left><CR><ESC><S-o>
inoremap ( ()<Left>
inoremap (<Enter> ()<Left><CR><ESC><S-o>
inoremap """<Enter> """<Left><CR><ESC><S-o>
inoremap " ""<Left>
" inoremap """<Space> """<Left>
inoremap ' ''<Left>
inoremap ` ``<Left>
inoremap <<Space> <><Left>
inoremap /<Space> //<Left>

" ;と:を入れ替える
nnoremap ; :
nnoremap ; :

" 入力しづらいキーをマッピング
nnoremap <Space>h ^
nnoremap <Space>l $
nnoremap <Space>/ *

" splitキーバインド
nnoremap s <Nop>
"" 画面移動
nnoremap sj <C-w>j
nnoremap sk <C-w>k
nnoremap sl <C-w>l
nnoremap sh <C-w>p
"" 画面サイズ変更
nnoremap s> <C-w>>
nnoremap s< <C-w><
nnoremap s= <C-w>=
nnoremap s+ <C-w>+
nnoremap s- <C-w>-
"" 画面入れ替え
nnoremap sH <C-w>H
nnoremap sJ <C-w>J
nnoremap sK <C-w>K
nnoremap sL <C-w>L
nnoremap sr <C-w>r

" ctags keybind
nnoremap <c-[> :pop<CR>

" ESC keybind
imap <C-f> <ESC><Right>
vmap <C-j> <ESC><Right>

" tab keybind
nnoremap <C-N> :tabn<CR>
nnoremap <C-P> :tabp<CR>

" 大文字小文字の誤爆を防ぐ
vnoremap u <Nop>
vnoremap U <Nop>
noremap gu <Nop>
noremap gU <Nop>

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" 補完
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

"コマンドライン補完拡張モード
set wildmenu
"シンタックスハイライト
" set syntax=on
syntax enable
" ファイルタイプでのインデント有効
filetype plugin indent on
" オムニ補完有効
set omnifunc=syntaxcomplete#Complete
