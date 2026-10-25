# Configuração da publicação deste sistema no servidor Windows.
# Lida por instalar.ps1, iniciar.ps1 e desinstalar.ps1 (que são iguais em todos os sistemas).

$NOME_SISTEMA = "Relatorio de margens aplicadas"   # SEM acentos: vira o nome da tarefa agendada e da regra de firewall
$PORTA_PADRAO = 3004                 # da tabela de orientacoes-projetos-ia.md (PORT no .env tem prioridade)
$TIPO         = "python"             # "python" ou "node"
$ENTRADA      = "servidor.py"        # arquivo principal, relativo à raiz do projeto (ex.: app.py, server/index.js)
$ARGUMENTOS   = "--producao"         # argumentos do modo produção (ex.: --producao) ou ""
$ROTA_TESTE   = "/"                  # rota que responde 200 com o sistema no ar (ex.: /, /api/saude)
$PASTAS_DADOS = @()                  # pastas onde o sistema grava; a conta SYSTEM recebe escrita (logs já incluso)
