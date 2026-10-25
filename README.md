# Relatório de margens aplicadas

Painel de margem por grupo das lojas Moura (SISMOURA). Mostra custo, venda, margem e markup dos produtos ativos, filtra por data de vigência, soma as vendas do mês e gera:

- **Exportar**: CSV dos produtos ou das vendas que estão na tela;
- **Relatório PDF**: produtos com última compra ou vigência na data do campo **Dia**.

Os bancos das lojas são consultados **somente para leitura**. Porta: **3004** (tabela de `orientacoes-projetos-ia.md`).

## Configuração

1. Copie `.env.example` para `.env` e preencha usuário, senha e o cadastro das lojas.
2. Em `LOJAS_ATIVAS`, liste os apelidos das lojas que devem aparecer no painel, separados por vírgula. Vazio = todas.
3. Instale as dependências: `python -m pip install -r requirements.txt`.

O `.env` tem senhas e endereços dos servidores: ele fica fora do Git.

## Rodar no próprio computador

Clique duas vezes em `Abrir Painel.bat` (ou `python servidor.py`). Abre em `http://localhost:3004`, acessível só nesta máquina.

## Publicar no servidor (Windows)

1. Copie a pasta do projeto para o servidor.
2. Tenha o Python 3.10+ instalado (python.org, 64-bit, marque "Add python.exe to PATH").
3. Crie o `.env` a partir do `.env.example`.
4. Clique duas vezes em `servidor\instalar.bat` e confirme o pedido de administrador.

Sobe sozinho ao ligar o computador (tarefa agendada "Relatorio de margens aplicadas (3004)"), reinicia se cair, e fica acessível em `http://NOME-DO-SERVIDOR:3004`. Log: `logs\servidor.log`.

- Para atualizar: copie os arquivos novos e rode o `instalar.bat` de novo.
- Para remover: `servidor\desinstalar.bat` (não apaga dados).

O painel mostra informação sensível (custos e margens) e não tem login: deixe-o acessível só pela rede interna.
