#!/bin/bash

# --- Script de Instalação Simplificada do RocksDB (Debian/Ubuntu) ---

# Função para checar erros
check_error() {
    if [ $? -ne 0 ]; then
        echo "❌ ERRO: Falha durante a execução de '$1'. Por favor, verifique a saída."
        exit 1
    fi
}

echo "🚀 Iniciando a instalação do RocksDB via gerenciador de pacotes..."

# 1. Atualiza a lista de pacotes
sudo apt update
check_error "apt update"

# 2. Instala a biblioteca RocksDB e os arquivos de desenvolvimento
#    - librocksdb-dev: Inclui os headers e links necessários para compilar bindings.
#    - libsnappy-dev, liblz4-dev, etc: Instala as bibliotecas de compressão que o RocksDB usa.
echo "⚙️ Instalando librocksdb-dev e bibliotecas de compressão..."
sudo apt install -y librocksdb-dev libsnappy-dev zlib1g-dev libbz2-dev liblz4-dev libzstd-dev
check_error "apt install"

# 3. Finalização e Instalação do Binding Python
echo "🎉 Bibliotecas nativas do RocksDB instaladas com sucesso!"
echo ""
echo "➡️ PRÓXIMO PASSO: Agora instale o binding Python com pip:"
echo "pip install rocksdb-py"