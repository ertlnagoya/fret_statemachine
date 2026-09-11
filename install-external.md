# 外部ツールのインストールコマンド
- 2026/8/13現在 動作確認

```bash
# READMEに記載された各種ツールやライブラリのインストール
sudo apt update
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
\. "$HOME/.nvm/nvm.sh"
nvm install v20.19
sudo apt install -y libgtk-3-0t64 libdrm2 libgbm1 libnss3 libx11-xcb1 libasound2t64

# コンパイラ等のインストール
sudo apt install build-essential 
sudo apt install -y build-essential 
gcc --version
g++ --version
make --version

# FRETのダウンロードと実行
mkdir ~/Documents #FRET実行のために必要
git clone https://github.com/NASA-SW-VnV/fret.git
cd fret/fret-electron/
npm run fret-install
npm start
```

```bash
# z3のインストール
cd ~/fret
mkdir external
cd external
wget https://github.com/Z3Prover/z3/archive/refs/tags/z3-4.14.1.tar.gz 
tar xvfz z3-4.14.1.tar.gz 
cd z3-z3-4.14.1/
python3 scripts/mk_make.py 
cd build/
make
make -j`nproc`
sudo make install
z3 -h #インストールされているか確認

# opamインストール（Kind2インストールに必要）
sudo apt install opam
opam --version
opam init #~/.opamが作成される

# Kind2インストール
cd ~/fret/external
mkdir kind2
cd kind2
opam switch create kind2-2.2.0 ocaml-base-compiler.4.14.2
eval $(opam env --switch=kind2-2.2.0)
opam install "kind2=2.2.0" --destdir=./ -j`nproc`
echo 'export PATH=$PATH:$HOME/fret/external/kind2/bin' >> ~/.bashrc
（再ログインまたはsource後）
kind2 --version #kind2 v2.2.0

# NuSMVインストール
cd ~/fret/external
wget https://nusmv.fbk.eu/distrib/2.7.0/NuSMV-2.7.0-linux64.tar.xz
tar xvf NuSMV-2.7.0-linux64.tar.xz 
echo 'export PATH=$PATH:$HOME/fret/external/NuSMV-2.7.0-linux64/bin' >> ~/.bashrc
echo 'export PATH=$PATH:$HOME/fret/tools/LTLSIM/ltlsim-core/simulator' >> ~/.bashrc
（再ログインまたはsource）
```