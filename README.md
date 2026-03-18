📚 Manga Scraper com Playwright

Este projeto é um scraper automatizado de mangás que utiliza Playwright para buscar, navegar e extrair informações diretamente do site WeebCentral.

Ele permite ao usuário pesquisar um mangá pelo nome, selecionar um capítulo específico (ou automaticamente o primeiro/último) e coletar todas as imagens desse capítulo.

🚀 Funcionalidades

🔍 Busca inteligente de mangás por nome

🎯 Sistema de pontuação para encontrar o melhor resultado

📖 Coleta completa de capítulos (incluindo lista completa quando disponível)

🔢 Extração e ordenação correta de capítulos (ex: 1, 1.5, 2…)

🎯 Seleção de capítulo por:

Número (ex: 10, 10.5)

Palavra-chave (primeiro, ultimo)

🖼️ Extração de todas as imagens do capítulo

🧠 Fallback inteligente caso a busca principal falhe

🔁 Evita duplicações de links automaticamente

🧠 Como funciona

O script:

Acessa o site usando Playwright

Tenta encontrar o mangá via múltiplas rotas de busca

Usa similaridade de texto para escolher o melhor resultado

Coleta todos os capítulos disponíveis

Permite selecionar um capítulo específico

Extrai todas as imagens da página do capítulo

🛠️ Tecnologias utilizadas

Python

Playwright

Regex (re)

urllib

difflib (similaridade de strings)
