# HELP WEB HEALTH API

Este repositorio contem o codigo-fonte, migracoes, testes e ferramentas locais.
O desenvolvimento nao depende da Shard ou de outra hospedagem. Use Python 3.11
ou 3.12 e mantenha os clones `helphealth-api` e `helphealth-web` lado a lado
para executar o roteiro conjunto de testes. Configuracoes reais de producao,
bancos, ambientes virtuais e ZIPs de deploy nao fazem parte do Git.

Backend do **HelpWeb Health**, uma API REST desenvolvida com FastAPI para gerenciamento de chamados de TI em instituicoes de saude publica, como hospitais, clinicas, laboratorios, UPAs e setores administrativos ligados ao atendimento.

O sistema foi pensado para melhorar a comunicacao entre funcionarios e equipe de tecnologia, especialmente em ambientes onde falhas de infraestrutura podem impactar o atendimento: computadores, impressoras, rede Wi-Fi, sistemas internos, leitores de codigo de barras, coletores, telefonia e outros equipamentos.

Importante: este projeto nao e um prontuario eletronico e nao deve armazenar dados de pacientes. O foco e suporte tecnico, infraestrutura de TI e organizacao dos atendimentos.

## Objetivo

A API centraliza o ciclo de vida dos chamados:

- cadastro e autenticacao de usuarios;
- perfil de usuario com telefone brasileiro validado, funcao, setor, unidade e preferencia de notificacao;
- alteracao de email e senha com codigo temporario de verificacao;
- recuperacao de conta por codigo enviado ao email cadastrado;
- abertura de chamados por funcionarios;
- classificacao por setor, categoria, equipamento, patrimonio e impacto operacional;
- acompanhamento por status;
- atribuicao e resolucao por tecnicos;
- comentarios e linha do tempo;
- notificacoes internas para equipe tecnica quando chamados sao criados ou reabertos;
- controle de perfis de acesso;
- indicadores para dashboard e relatorios filtrados.

Essa organizacao ajuda a reduzir perda de informacao, ligaÃ§Ãµes informais sem registro e dificuldade de priorizacao em setores sensiveis da saude publica.

## Perfis de usuario

O sistema trabalha com tres perfis:

- `user`: funcionario comum. Pode abrir chamados, acompanhar os proprios chamados, comentar, confirmar o fechamento de resolvidos e cancelar antes do primeiro atendimento. Nao pode excluir, recuperar ou reabrir chamados ja assumidos.
- `technician`: tecnico de TI. Pode visualizar chamados atribuidos a ele e chamados abertos/reabertos sem tecnico na fila compartilhada, assumir atendimentos, resolver chamados e consultar indicadores pessoais.
- `admin`: administrador. Pode gerenciar usuarios, visualizar indicadores e executar acoes administrativas.

Endpoints de dashboard e relatorios sao protegidos para `technician` e `admin`. O administrador recebe a visao global; o tecnico recebe somente metricas dos chamados atribuidos a ele. A fila compartilhada aparece separadamente para operacao e nao contamina os indicadores pessoais. O escopo e aplicado na API, inclusive em detalhes, timeline, listagem e PDF, evitando que o frontend seja a unica barreira.

### Cancelamento e recuperacao de chamados

- `PATCH /api/v1/tickets/{id}/cancel`: exige sessao, CSRF e autoria do chamado.
  So permite status `open`, sem tecnico e sem evento `ASSIGNED` no historico.
  Limpar o tecnico de um chamado que ja foi assumido nao libera cancelamento.
- Assumir e cancelar usam atualizacoes condicionais no banco: uma solicitacao
  concorrente nao pode assumir um chamado cancelado nem cancelar um assumido.
- O cancelamento e uma exclusao logica com status `cancelled`, evento `CANCELLED`
  e auditoria `ticket.cancelled`. Nao apaga historico, comentarios ou imagens.
  Remove notificacoes e nao entra na fila, listas operacionais, indicadores ou PDF.
- Excluidos e cancelados continuam no arquivo de consulta, com o escopo de
  visibilidade existente. Recuperacao, exclusao e reabertura exigem administrador.
- Recuperar um cancelado devolve o status `open` e calcula novo prazo SLA.
  Recuperar outro chamado excluido preserva o status original. O evento
  `RECOVERED` registra a transicao e os eventos anteriores sao mantidos.
- O detalhe informa `can_cancel` calculado na API para o usuario autenticado;
  ocultar um botao nao substitui a validacao do endpoint.
- Os totais da fila e de atendimentos em andamento sao separados das listas
  resumidas do dashboard, limitadas a oito itens. Excluidos nao entram em ambos.

Nao e necessaria migracao de schema para esta regra: `status` ja e texto e os
campos de exclusao logica ja existem. A validacao de enum aceita `cancelled`.

## Principais recursos

- API REST com FastAPI.
- Regras sensiveis centralizadas no backend: permissao, SLA, mudanca de status, filtros, limites de upload, verificacao de email, rate limit e calculos de relatorio.
- Autenticacao JWT com PyJWT.
- Criptografia de senha com Passlib/Bcrypt.
- Sessao entregue somente em cookie HttpOnly, com expiração, `jti`, `iss`, `aud`, `nbf`, versão de sessão e revogação no logout.
- Proteção CSRF por cookie de duplo envio para mutações feitas com a sessão do navegador.
- Troca de senha e email protegida por codigo temporario enviado por email.
- Recuperacao de conta com resposta publica generica para reduzir enumeracao de usuarios.
- Logout com revogacao do JWT atual por `jti`.
- Rate limit global por IP + usuario/token, alem do bloqueio progressivo de falhas no contexto IP + email. Assim, um erro de uma conta nao bloqueia outros usuarios da mesma rede. A cada cinco falhas, o bloqueio segue 5s, 10s, 15s, 20s, 1min, 5min, 30min, 2h e chega a 6h nas faixas mais altas. Durante o bloqueio, qualquer tentativa recebe 429 sem executar bcrypt; outro contexto de login continua podendo autenticar.
- Redis e opcional: sem `REDIS_URL`, os limites usam memoria local; com `REDIS_URL`, o rate limit global e os limites de login/recuperacao passam a ser distribuidos entre instancias.
- Headers de seguranca contra clickjacking e exposicao indevida de respostas.
- Logs de SMTP mascaram o email de destino.
- Logs sao emitidos em formato textual legivel, definido na politica versionada.
- Tentativas de codigo invalido/expirado ficam registradas para auditoria sem salvar o codigo digitado.
- Headers de proxy so sao usados para identificar IP quando `TRUSTED_PROXY_HOPS` e configurado explicitamente. Quando habilitado, a API prefere `CF-Connecting-IP`, depois `X-Real-IP` e por fim `X-Forwarded-For`.
- CORS aceita somente as origens declaradas em `ALLOWED_ORIGINS`; `*` e rejeitado. Em modo seguro, origens externas precisam usar HTTPS.
- PostgreSQL remoto força `sslmode=require` quando a URL tenta omitir ou desativar TLS.
- Swagger/OpenAPI desligado por padrao em producao e com protecao opcional por usuario/senha quando habilitado.
- Health check publico simples, sem expor diagnostico do banco por padrao.
- Controle de permissao por perfil, com escopo de chamados aplicado no backend para impedir IDOR entre tecnicos.
- SQLAlchemy ORM para facilitar migracao futura de banco.
- Alembic para versionamento do schema.
- SQLite para desenvolvimento, testes e deploy simples em instancia unica.
- Lock de inicializacao para reduzir corrida entre migracoes/admin inicial quando mais de um processo sobe ao mesmo tempo.
- Suporte direto a SQLite no desenvolvimento e PostgreSQL no deploy.
- Pool de conexoes configuravel para reduzir latencia com PostgreSQL.
- Chamados com setor, categoria, equipamento, codigo de patrimonio, impacto operacional e SLA.
- Ate 3 fotos opcionais do problema no chamado, recebidas ja compactadas pelo frontend e validadas novamente no backend.
- Foto de perfil do usuario.
- Avisos operacionais por setor, gerenciados somente por administradores.
  Criacao e edicao validam texto, nivel, setores oficiais e prazo com fuso horario.
  Edicao preserva autor, data de publicacao e estado de ativacao. Setores antigos
  ja vinculados podem ser mantidos, mas novos destinos devem estar ativos.
  Avisos vencidos nao podem ser reativados sem alterar ou remover o prazo.
  Edicao (`PATCH /api/v1/admin/maintenance-notices/{id}`), exclusao
  (`DELETE /api/v1/admin/maintenance-notices/{id}`) e ativacao/desativacao
  exigem sessao de administrador e CSRF, com registro de auditoria.
- Avisos possuem publico `all`, `users` ou `technicians`, aplicado pela API
  junto ao setor e ao periodo de validade. Administradores podem consultar
  e gerenciar todos os publicos.
- Leitura persistente por conta e versao em `maintenance_notice_reads`.
  `POST /api/v1/maintenance-notices/{id}/read` recebe apenas `revision`;
  o usuario vem da sessao autenticada. Exige CSRF, aplica escopo de visibilidade
  e e idempotente. Versoes antigas recebem 409 sem marcar a versao nova.
  A listagem publica retorna somente avisos ativos nao lidos pela conta;
  a administrativa continua mostrando todos. Alterar conteudo, nivel, publico,
  setores ou prazo gera nova versao. Salvar sem mudancas nao redefine leituras.
  Migracao `j0k1l2m3n4o5` preserva avisos existentes com publico geral e versao 1.
- Timeline de eventos e comentarios.
- Notificacoes persistentes por usuario para tecnicos e administradores.
- Relatorios por periodo, status, prioridade, setor, categoria, equipamento, impacto, SLA, idade da fila, volume diario, solicitantes recorrentes e reaberturas.
- Exportacao de relatorio gerencial em PDF real pela API, com layout A4 horizontal, blocos compactos, resumo Top N + "Outros" e download direto pelo navegador.

## Estrutura principal

```text
helphealth-api/
  app/
    api/              Rotas da API
    core/             Configuracoes, autenticacao, permissoes e utilitarios centrais
    db/               Sessao do banco e modelos SQLAlchemy
    middlewares/      Protecoes e interceptadores HTTP por responsabilidade
    schemas/          Schemas Pydantic
    services/         Regras de negocio separadas por dominio
      audit/          Registro de eventos de auditoria
      auth/           Login, tokens, rate limit de conta e codigos de verificacao
      messaging/      Envio de email por SMTP
      notifications/  Notificacoes internas para tecnicos e administradores
      reports/        Dashboard, metricas e relatorios
      system/         Bootstrap e controle de inicializacao
      tickets/        Chamados, comentarios, timeline e permissoes de visualizacao
      users/          Cadastro, perfil e administracao de usuarios
  alembic/            Migracoes do banco
  main.py             Entrada da aplicacao
  requirements.txt    Dependencias Python, incluindo ReportLab para gerar PDF
  requirements-postgres.txt Atalho compativel para instalacao das dependencias
  tools/             Utilitarios locais, incluindo migracao SQLite -> PostgreSQL
  tests/             Testes de autenticacao, autorizacao, CSRF, CORS, headers e banco
  .env.example        Exemplo de variaveis de ambiente
```

## Variaveis de ambiente

Crie um arquivo `.env` na raiz da API usando `.env.example` como base:

```env
DATABASE_URL=sqlite:///./helphealth.db
# Para PostgreSQL na hospedagem:
# DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
SECRET_KEY=gere_uma_chave_aleatoria_com_32_caracteres_ou_mais
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=troque_esta_senha_antes_de_publicar
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
SMTP_USERNAME=
SMTP_PASSWORD=
REDIS_URL=
TRUSTED_PROXY_HOPS=0
```

Descricao:

- `DATABASE_URL`: endereco do banco. Para SQLite local, use `sqlite:///./helphealth.db`. Para PostgreSQL, use a URL fornecida pelo seu provedor, no formato `postgresql://usuario:senha@host:porta/banco?sslmode=require`. URLs `postgres://` sao normalizadas para `postgresql://`. Quando o host do PostgreSQL nao for local, a API exige `sslmode=require` mesmo que a URL original nao traga SSL.
- `SECRET_KEY`: chave usada para assinar tokens JWT. A API recusa iniciar com chave de exemplo ou menor que 32 caracteres.
- `AUTH_COOKIE_SECURE`: use `false` somente em teste local HTTP. Em producao HTTPS, use `true`.
- `AUTH_COOKIE_SAMESITE`: use `lax` em teste local ou em producao no mesmo site. Use `none` junto com `AUTH_COOKIE_SECURE=true` apenas quando frontend e API estiverem em sites diferentes. Alguns navegadores bloqueiam cookies de terceiros; prefira publicar ambos no mesmo site.
- `AUTH_COOKIE_DOMAIN`: normalmente fica vazio. Configure dominio compartilhado apenas se souber exatamente o dominio-base aceito pelo navegador.
- Os nomes dos cookies, algoritmo JWT, expiracao da sessao e header CSRF ficam fixos em `app/core/security_policy.py`.
- `GET /api/v1/auth/csrf`: rota autenticada que devolve somente o token CSRF da sessao para o frontend cross-origin. Ela nao devolve o JWT nem dados sensiveis.
- `ADMIN_EMAIL`: e-mail inicial do administrador criado automaticamente.
- `ADMIN_PASSWORD`: senha inicial do administrador. A API recusa iniciar com senha de exemplo ou menor que 12 caracteres.
- `ALLOWED_ORIGINS`: dominios autorizados a chamar a API pelo navegador. Use a URL exata, sem barra final, e nunca use `*` em producao.
- SMTP usa Gmail na porta 587 com TLS; somente `SMTP_USERNAME` e `SMTP_PASSWORD` ficam no ambiente. Os prazos de codigo e recuperacao sao politicas no codigo.
- Rate limit por rota: os limites especificos de autenticacao, cadastro, dashboard, relatorios, chamados, notificacoes, administracao e webhook ficam descritos na secao de seguranca e centralizados em `app/core/security_policy.py`. Falhas de login: a cada grupo de 5 erros o bloqueio do contexto IP + email avanca na tabela progressiva da politica, chegando a 6 horas nas faixas mais altas.
- `REDIS_URL`: opcional. Quando configurada, o rate limit global e os limites de login/recuperacao passam a ser compartilhados entre instancias da API. Sem Redis, os limites continuam locais em memoria.
- Limites de concorrencia, corpo, URL, headers, imagens e parametros do Redis ficam em `app/core/security_policy.py`.
- `TRUSTED_PROXY_HOPS`: quantidade de proxies confiaveis usados para aceitar headers de IP real. O padrao `0` ignora headers enviados pelo cliente. Use `1` somente se a hospedagem confirmar que sobrescreve ou concatena esses headers corretamente.
- O lock de inicializacao fica ao lado do SQLite ou no diretorio temporario quando o banco e PostgreSQL.
- As migracoes no `main.py` ficam habilitadas por codigo e protegidas por tempos de lock definidos na politica.

Nunca suba o arquivo `.env` para o GitHub. Ele pode conter senhas, chaves e URLs privadas.

### Catalogo oficial e relatorios

- Setores e categorias de novos chamados sao selecionados no catalogo oficial.
  A API recusa nomes desconhecidos ou inativos, inclusive em envios diretos.
- Administradores gerenciam o catalogo em **Setores e categorias**: adicionar,
  editar, excluir quando nao utilizado, desativar e reativar. Os nomes equivalentes por acento, caixa e espacos nao
  podem ser cadastrados duas vezes. Desativar nao altera os chamados antigos.
- Renomear atualiza a classificacao dos chamados vinculados (inclusive os
  arquivados), sem mudar comentarios, eventos ou datas operacionais. Para
  setores, tambem atualiza os setores equivalentes nos perfis e avisos.
  A alteracao e registrada na auditoria, com nome anterior e totais afetados.
- Excluir e bloqueado quando houver chamados, perfis ou avisos vinculados;
  nesse caso, o administrador deve desativar o cadastro. A API nao apaga
  chamados para excluir um item do catalogo.
- A migracao `i9j0k1l2m3n4` cria o catalogo com os 12 setores e as 12 categorias
  inicialmente sugeridos pelo sistema. Nomes livres antigos nao sao importados
  automaticamente como opcoes oficiais; o administrador deve cadastrar os
  nomes legitimos que faltarem.
- Relatorios agrupam grafias equivalentes, inclusive em filtros e no PDF.
  Erros de digitacao nao sao mesclados automaticamente com outro nome.
- A tela mostra os seis itens de maior volume e soma os demais em **Outros**.
  O PDF tambem consolida os demais itens, preservando todos os totais.
- A evolucao cobre o periodo completo com ate oito intervalos, por dia, semana,
  mes, trimestre ou ano. Periodos muito longos usam intervalos de anos.
- A tabela de atendimento lista apenas contas com perfil de tecnico, tem busca
  e paginacao na tela e resumo no PDF. Atendimentos de administradores continuam
  nos totais gerais, com sua quantidade indicada separadamente.
- Rotas: `GET /api/v1/ticket-catalog/` (contas verificadas),
  `POST /api/v1/admin/ticket-catalog/` e
  `PATCH /api/v1/admin/ticket-catalog/{id}/active`,
  `PATCH /api/v1/admin/ticket-catalog/{id}` e
  `DELETE /api/v1/admin/ticket-catalog/{id}` (administradores, com CSRF).

### Segurança local e CI

Depois de instalar as dependências de desenvolvimento, rode:

```bash
python -m pytest -q
python -m compileall -q app main.py
python -m pip check
pip-audit -r requirements-dev.txt
bandit -r app main.py -ll -iii
```

O workflow em `.github/workflows/security.yml` executa essas verificações principais em pull requests e pushes para `main`. O Dependabot em `.github/dependabot.yml` acompanha atualizações de pacotes Python e GitHub Actions.

No Windows, a verificacao equivalente usa o interpretador do `.venv` e tambem
pode validar o frontend local:

```powershell
.\tools\local_security_check.ps1
.\tools\local_full_check.ps1
.\tools\local_full_check.ps1 -IncludeBrowserTests
```

O roteiro conjunto executa os controles da API, lint, testes unitarios, build
e auditoria do frontend. A opcao `-IncludeBrowserTests` acrescenta os testes
de interface e PWA com dados simulados, servindo o build local e encerrando
o servidor ao terminar. Feche outro frontend na porta 5173 antes dessa opcao.
Requer Node.js 22.12 ou superior e Edge instalado (ou Chrome, selecionado por
`$env:UI_TEST_BROWSER = "chrome"`). Os scripts funcionam mesmo quando chamados
de outro diretorio. O
`pip-audit` consulta o servico online de advisories; se a rede estiver
indisponivel, a etapa falha com timeout explicito e nao deve ser interpretada
como auditoria concluida.

Os testes de release incluem sessoes independentes disputando cancelamento,
atribuicao e recuperacao, rollback de falha de auditoria, acesso a dados de
outra conta, CSRF nas novas operacoes administrativas e entradas JWT invalidas.
Usam banco temporario; nao se conectam ao PostgreSQL da hospedagem.

### Dependencias e banco de dados

`requirements.txt` separa dependencias diretas das transitivas, todas com
versao fixa. As transitivas sao usadas pelos frameworks e nao devem ser
retiradas apenas por nao existir um import direto. Pillow e charset-normalizer
fazem parte da geracao de PDFs; colorama e instalado somente no Windows.
`requirements-dev.txt` acrescenta testes e verificadores apenas no ambiente de
desenvolvimento. `requirements-postgres.txt` e um atalho de compatibilidade,
nao uma segunda lista de pacotes.

PostgreSQL usa psycopg2-binary no ambiente de producao. SQLite vem da
biblioteca padrao do Python, nao instala um driver extra e permanece apenas
como opcao local e banco temporario dos testes. SQLAlchemy e Alembic sao
necessarios tambem para PostgreSQL. A ferramenta historica de importacao do
SQLite fica em `tools/` e nao e incluida no ZIP de deploy.

Redis, fila e worker WhatsApp foram preservados para ativacao futura. O cliente
Evolution usa a biblioteca padrao; nao necessita SDK adicional. Os testes de
arquitetura conferem imports, arvore transitiva, versoes e ausencia de pacotes
legados sem uso. python-jose, ecdsa e auxiliares antigos nao sao dependencias
da autenticacao atual, que usa PyJWT com HS256.

Em 03/10/2026, PyJWT foi atualizado de 2.13.0 para 2.15.1 para incorporar
correcoes publicadas pelo mantenedor. A autenticacao continua limitada a
HS256 e nao aceita um algoritmo escolhido pelo cliente.
O cliente Evolution nao segue redirecionamentos, evitando encaminhar sua
chave a outro endereco. WhatsApp/Redis continuam opcionais e desativados.

Bandit deve ser revisado tambem sem filtros antes de releases: alertas de
baixa severidade sobre subprocess de migracao (argumentos fixos, sem shell),
marcadores `token_type` e nomes de finalidade nao sao senhas embutidas.
O bind `0.0.0.0` e intencional no servico hospedado; restricao de acesso
depende do proxy/firewall. Nao existe garantia de ausencia de vulnerabilidades.

Sem SMTP, o codigo de MFA de login de administrador/tecnico pode ser mostrado
no terminal somente com SQLite e origens HTTP estritamente locais. Codigos de
cadastro e recuperacao nao sao expostos dessa forma. Para esses fluxos e para
MFA em producao, configure SMTP real; os testes automatizados simulam o envio.

### SMTP com Gmail

Para usar sua propria conta Gmail, ative a verificacao em duas etapas e gere
uma senha de app. Configure apenas no `.env` privado ou ambiente da hospedagem:

```env
SMTP_USERNAME=sua-conta@gmail.com
SMTP_PASSWORD=sua_senha_de_app_do_google_sem_espacos
```

Use a senha de app de 16 caracteres, nao a senha normal da conta Google. Se voce copiar a senha com espacos, a API remove os espacos automaticamente; o ideal e salvar sem espacos no painel.

## Como rodar localmente

Entre na pasta da API:

```bash
cd helphealth-api
```

Crie e ative o ambiente virtual:

```bash
python -m venv .venv
```

No Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear a ativacao:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Instale as dependencias:

```bash
python -m pip install -r requirements-dev.txt
```

Crie o arquivo `.env` sem substituir uma configuracao existente:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Antes de iniciar, coloque a chave gerada em `SECRET_KEY` e defina uma senha
propria em `ADMIN_PASSWORD` (12 caracteres ou mais, no maximo 72 bytes).
Os exemplos dessas duas variaveis sao recusados pela API. `admin@example.com`
serve somente para demonstracao local; use email real para receber mensagens.
Deixe SMTP, Redis e WhatsApp sem configuracao no teste local inicial. O
administrador e criado na primeira inicializacao; modificar a variavel depois
nao altera a senha de uma conta ja existente.

Execute a API:

```bash
python main.py
```

## Testes automatizados locais

Os testes de desenvolvimento ficam separados das dependencias de producao.
Eles usam um SQLite temporario, nao alteram `helphealth.db` e mantem
`WHATSAPP_ENABLED=false`, portanto nao acessam Redis, Evolution API ou SMTP.

Instale as dependencias de desenvolvimento uma vez:

```bash
python -m pip install -r requirements-dev.txt
```

Execute a suite:

```bash
pytest
```

Antes de publicar uma alteracao, valide tambem a migration em uma copia do
banco local e compile a API:

```bash
DATABASE_URL=sqlite:///./helphealth_test.db python -m alembic upgrade head
python -m compileall -q app alembic
```

No Windows PowerShell, use `$env:DATABASE_URL=...` antes do comando. Nunca
execute migrations de teste sobre o banco de producao sem uma copia.

A API ficara disponivel em:

```text
http://127.0.0.1:8000
```

Documentacao interativa permanece desabilitada nesta versao por politica de codigo:

```text
http://127.0.0.1:8000/docs
```

## Migracoes do banco

O projeto usa Alembic. Ao iniciar pelo `main.py`, as migracoes sao aplicadas automaticamente por politica de codigo.

No deploy simples com SQLite, `main.py` usa um lock de arquivo antes de rodar migracoes e criar o admin inicial. Isso reduz risco de corrida se a hospedagem iniciar mais de um processo ao mesmo tempo. Os tempos do lock ficam em `app/core/security_policy.py`.

As migrations atuais foram revisadas para funcionar tanto em SQLite quanto em PostgreSQL, incluindo campos booleanos usados na verificacao de email.

Para aplicar manualmente:

```bash
alembic upgrade head
```

### Usando PostgreSQL em producao

No ambiente da API, configure `DATABASE_URL` com o PostgreSQL do seu provedor.
Esse ajuste nao requer alterar a arquitetura nem o codigo. Exemplo:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
```

As migracoes rodam automaticamente no boot e os limites do pool ficam na
politica versionada do backend.

Depois reinicie ou faça novo deploy da API. Na primeira subida com o banco vazio, o Alembic cria as tabelas e o `main.py` cria o admin inicial usando `ADMIN_EMAIL` e `ADMIN_PASSWORD`.

Se voce quiser preservar os dados do SQLite antigo, rode primeiro em ambiente local ou em um terminal seguro:

```bash
python tools/migrate_sqlite_to_postgres.py --sqlite sqlite:///./helphealth.db --postgres "postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require"
```

O script recusa copiar para um PostgreSQL que ja tenha dados. Use `--replace` somente se tiver certeza de que pode limpar o destino antes da copia.

## Seguranca aplicada

- A sessao principal do frontend usa cookie HttpOnly, Secure e SameSite, emitido pela API.
- O backend ainda consegue validar token Bearer para compatibilidade tecnica, mas o frontend nao salva JWT em `localStorage` ou `sessionStorage`.
- Cada JWT possui `jti`; ao fazer logout, o token atual entra na tabela `token_blocklist` ate expirar.
- Endpoints autenticados rejeitam tokens expirados, sem `jti`, revogados ou emitidos antes da versao atual de sessao do usuario.
- Troca/recuperacao de senha e alteracao administrativa de papel/email invalidam sessoes antigas pelo campo `session_version`.
- A aplicacao recusa iniciar com `SECRET_KEY` fraca/de exemplo ou `ADMIN_PASSWORD` fraca/de exemplo.
- Login usa mensagem generica para reduzir enumeracao de usuario.
- Login executa uma verificacao bcrypt equivalente mesmo quando o email nao existe, reduzindo enumeracao por diferenca de tempo.
- Bloqueio de login considera tambem a conta/e-mail, nao apenas IP, reduzindo bypass por spoofing de cabecalho.
- Rotas publicas e consultas de polling possuem limites proprios para reduzir abuso.
- A autenticacao tambem e declarada no nivel dos routers: dashboard e relatorios exigem tecnico ou administrador; administracao exige administrador; notificacoes, comentarios e demais operacoes de chamados exigem usuario autenticado; o webhook da Evolution usa segredo proprio, sem aceitar sessao de navegador.
- O rate limit e separado por operacao e usa a combinacao de escopo, IP e identidade da sessao quando disponivel: login `40/min`, recuperacao `20/min`, cadastro `10/min`, dashboard `30/min`, relatorio JSON `20/min`, PDF `5/min`, leitura de chamados `120/min`, escrita de chamados/comentarios `40/min`, notificacoes `60/min`, leitura administrativa `30/min`, escrita administrativa `20/min` e webhook `120/min`. As capacidades e taxas ficam centralizadas em `app/core/security_policy.py`; a instancia local usa Token Bucket e Redis permanece opcional para distribuicao futura.
- A API limita tamanho de corpo, URL e headers antes de processar a requisicao, inclusive quando o corpo chega em stream sem `Content-Length`.
- A API possui limite de concorrencia por instancia para reduzir saturacao por rajadas de requests.
- `REDIS_URL` pode ser configurada para rate limit distribuido entre instancias, incluindo login e recuperacao de conta. Sem Redis, a API usa limite local em memoria, adequado para uma unica instancia.
- Cadastro publico tambem evita confirmar diretamente se um email ja existe.
- Listagens usam respostas resumidas para nao trafegar imagem/base64 ou descricao completa sem necessidade.
- Notificacoes sao salvas por destinatario e retornadas apenas para o usuario autenticado, evitando IDOR.
- Notificacoes de chamados nao carregam descricao completa, imagem, email ou dados sensiveis; mostram apenas resumo curto com setor e titulo.
- Timeline de chamados nao expõe email do autor, apenas dados minimos para identificar o registro.
- Rotas usam ORM SQLAlchemy e enums/whitelists para filtros e ordenacao, evitando SQL dinamico.
- CORS usa lista fixa de origens em `ALLOWED_ORIGINS`; em producao, evite `*`.
- Requisicoes para `/api/` vindas de `Origin` fora da lista autorizada sao bloqueadas tambem no middleware da API.
- IP de log/rate limit usa headers de proxy somente quando `TRUSTED_PROXY_HOPS` e habilitado. A ordem de preferencia e `CF-Connecting-IP`, `X-Real-IP` e `X-Forwarded-For`.
- `/docs`, `/redoc`, `/openapi.json`, `/health/db` e o endpoint de diagnostico de proxy ficam desabilitados por politica de codigo; `/health` continua disponivel para a hospedagem.
- Uploads em Data URL sao validados no backend por tipo permitido, base64 valido, assinatura real de imagem e tamanho. O limite foi ajustado para aceitar fotos de celular compactadas sem permitir imagens brutas excessivas no banco SQLite.
- Codigos temporarios de email/senha sao armazenados apenas como HMAC, nao em texto puro.
- O backend nao grava senhas, tokens JWT, codigo digitado ou email completo em logs; codigos de verificacao tambem nao sao liberados por variavel de ambiente.
- Novas senhas exigem pelo menos 10 caracteres, letras e numeros, e rejeitam padroes previsiveis.
- A API impede que um administrador altere o proprio papel ou remova o papel do ultimo administrador restante.
- Conexoes PostgreSQL remotas usam `sslmode=require` por padrao, mesmo quando a URL original nao informa SSL.
- Em 19/07/2026, as dependencias de producao do `requirements.txt` foram atualizadas e auditadas com `pip-audit`, sem vulnerabilidades conhecidas no resultado.
- O projeto pode usar SQLite em deploy simples, mas PostgreSQL e recomendado para ambiente real por oferecer melhor concorrencia, backup, isolamento e recursos de seguranca do banco gerenciado.
- O arquivo SQLite nao e criptografado integralmente por padrao; para dados reais, prefira PostgreSQL gerenciado com criptografia em repouso, backup e controle de acesso.
- A listagem administrativa de usuarios retorna email mascarado e nao envia foto/base64 em massa.
- O endpoint `/api/v1/admin/network-debug` permanece desabilitado no codigo.
- Telefones de perfil e cadastro aceitam apenas numeros do Brasil no formato DDD + numero, sem DDI ou `+55`.
- Novos cadastros precisam confirmar email antes de abrir chamados.
- Eventos sensiveis sao registrados em trilha de auditoria persistente (`audit_events`) sem gravar senha, token, codigo temporario ou email completo.
- Redis nao e obrigatorio nesta versao. Quando disponivel, pode ser configurado somente por `REDIS_URL` para rate limit distribuido e fila WhatsApp; os nomes de chaves e timeouts ficam no codigo.
- O repositorio inclui workflow de GitHub Actions para compilar o backend e executar `pip-audit`.

## Recuperacao de conta

O fluxo de recuperacao de conta permite redefinir senha sem estar logado:

1. O usuario informa o email cadastrado e a nova senha desejada.
2. A API retorna uma mensagem generica, sem confirmar publicamente se o email existe.
3. Se a conta existir, um codigo temporario e enviado por email.
4. O usuario informa o codigo recebido e a nova senha e a API redefine a senha.

Endpoints:

```text
POST /api/v1/auth/password/recovery/request
POST /api/v1/auth/password/recovery/confirm
```

Esse fluxo usa a mesma tabela de verificacao temporaria de email/senha, com proposito separado para recuperacao.

## Notificacoes internas

Quando um funcionario abre um chamado ou um administrador reabre um chamado resolvido/fechado, a API cria notificacoes para tecnicos conforme o vinculo e o tipo do evento. O administrador nao e destinatario da caixa comum de notificacoes, mas pode consultar o historico global pela area administrativa. A regra fica no backend, nao no frontend.

Endpoints:

```text
GET /api/v1/notifications/
PATCH /api/v1/notifications/{notification_id}/read
PATCH /api/v1/notifications/read-all
```

Regras principais:

- cada notificacao possui um `recipient_id`;
- a listagem sempre filtra pelo usuario autenticado;
- marcar como lida tambem exige que a notificacao pertenca ao usuario logado;
- o limite de retorno vai ate 50 registros por chamada;
- notificacoes relacionadas a tickets ou usuarios removidos sao limpas/ajustadas pelos servicos de negocio.

A tela administrativa usa o endpoint agrupado abaixo para mostrar um resumo por
chamado, em vez de carregar eventos soltos sem limite no navegador:

```text
GET /api/v1/admin/ticket-events?search=&skip=0&limit=20
```

Essa rota exige `admin`, pesquisa por codigo numerico, codigo formatado, titulo,
descricao, setor ou categoria e retorna no maximo 50 chamados por pagina. O
historico detalhado continua sendo carregado sob demanda pela timeline protegida
do chamado, evitando uma consulta N+1 e reduzindo o volume de dados exposto.

## Dados ficticios para testes locais

O arquivo `tools/generate_demo_data.py` cria dados variados para testar
dashboard, relatorios, fila, busca, permissao, pagina de eventos e timeline.
Por seguranca, o script aceita somente `DATABASE_URL` SQLite e nunca deve ser
executado contra PostgreSQL ou contra a hospedagem.

Com a API parada e dentro da pasta do backend, use:

```powershell
python -m alembic upgrade head
python tools/generate_demo_data.py --count 200
```

As contas criadas usam emails `@example.com`, reservados para exemplos, possuem email confirmado e a
senha local de teste `DemoSenha123!`. O script cria um administrador demo,
tecnicos demo e usuarios solicitantes. Os chamados recebem distribuicao de
status, prioridades, impactos, setores, categorias, tecnicos, eventos e alguns
comentarios, sem imagens.

Para substituir somente os dados ficticios e gerar uma nova distribuicao:

```powershell
python tools/generate_demo_data.py --count 200 --reset
```

Os registros de demonstracao possuem o prefixo `DEMO-` e o script nao remove
usuarios ou chamados reais. O `--reset` tambem reconhece o prefixo antigo
`[DEMO]` para limpar uma carga criada por uma versao anterior do script. Mesmo
assim, mantenha um backup do banco local antes de usar `--reset`.

## Diagnostico de IP real na hospedagem

A rota abaixo existe para confirmar como a hospedagem encaminha o IP real do visitante para a API, mas fica desligada por padrao:

```text
GET /api/v1/admin/network-debug
```

Nesta versao a rota permanece desabilitada no codigo depois da validacao do
proxy. Para uma nova investigacao, ela deve ser habilitada somente em uma
alteracao local controlada e nunca como variavel de ambiente de producao.

Mesmo habilitada, ela exige login como administrador e retorna apenas:

- IP da conexao recebida por Uvicorn;
- IP resolvido pela funcao `get_client_ip`;
- valor atual de `TRUSTED_PROXY_HOPS`;
- headers `X-Forwarded-For`, `X-Real-IP`, `CF-Connecting-IP` e `Forwarded`.

A rota nao retorna `Cookie`, `Authorization` nem outros headers sensiveis. Use essa informacao para decidir se `TRUSTED_PROXY_HOPS=1` e seguro. Nao habilite `TRUSTED_PROXY_HOPS=1` no chute: se a hospedagem nao sobrescrever os headers de proxy corretamente, um cliente poderia falsificar o IP e enfraquecer o rate limit.

Mantenha `TRUSTED_PROXY_HOPS=0` no desenvolvimento local e se a API receber
conexao direta. Em qualquer provedor, ajuste esse valor apenas depois de
confirmar quantos proxies confiaveis existem e que eles removem ou sobrescrevem
headers enviados pelo cliente. Nao reutilize a configuracao de outro ambiente
sem essa verificacao.

## Logs e privacidade

Os logs evitam expor dados sensiveis desnecessarios. Emails de login e envio SMTP sao mascarados, por exemplo `an***9@gmail.com`. Por seguranca, a API ignora `X-Forwarded-For`, `X-Real-IP` e `CF-Connecting-IP` por padrao. Configure `TRUSTED_PROXY_HOPS=1` apenas depois de confirmar o comportamento do proxy da hospedagem.

Os logs HTTP usam nomes de acao para facilitar a leitura no terminal, por exemplo `ticket.create`, `auth.login`, `ticket.resolve`, `admin.ticket_events`, `notification.list` e `report.overview`. Cada evento informa o resultado, o status com descricao (`401 Unauthorized`, por exemplo), o metodo, a rota, a duracao, o IP tecnico resolvido, a identidade mascarada e o `request_id` para correlacionar uma falha entre os componentes. Requisicoes automaticas de `/health` e preflight `OPTIONS` bem-sucedidas ficam em `DEBUG`; erros continuam aparecendo em `WARNING` ou `ERROR`.

No formato textual, os eventos da aplicacao recebem uma linha em branco curta para facilitar a leitura no terminal. Stack traces detalhados permanecem desligados por politica para nao despejar dados de entrada ou caminhos internos no log comum.

## Padrao de status HTTP

A API segue o padrao REST principal:

- `200 OK`: consultas, login, logout, atualizacoes e acoes que retornam corpo de resposta.
- `201 Created`: criacao de usuario, chamado e comentario.
- `204 No Content`: exclusoes feitas por administrador ou cancelamentos pelo autor antes do atendimento, sem corpo de resposta.
- `400 Bad Request`: regra de negocio invalida, como codigo incorreto ou status incompatível.
- `401 Unauthorized`: usuario nao autenticado ou credenciais invalidas.
- `403 Forbidden`: usuario autenticado sem permissao para a acao.
- `404 Not Found`: recurso inexistente ou rota administrativa desabilitada.
- `413/414/415/422`: limites de corpo/URL/tipo de conteudo e validacao de campos.
- `429 Too Many Requests`: limite de requisicoes atingido.
- `503 Service Unavailable`: limite de concorrencia da instancia atingido.

## Admin inicial

O administrador inicial e criado automaticamente na primeira execucao usando `ADMIN_EMAIL` e `ADMIN_PASSWORD`. Nao existe seed de dados ficticios no boot de producao; a carga opcional para testes locais fica isolada em `tools/generate_demo_data.py`, aceita somente SQLite e usa contas marcadas como demonstracao.

## Hospedagem opcional

O mesmo codigo pode ser hospedado na Shard, em uma VPS ou outro provedor com
Python e PostgreSQL. Configure segredos no ambiente, nunca no repositorio:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
SECRET_KEY=gere_uma_chave_aleatoria_com_32_caracteres_ou_mais
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
ADMIN_EMAIL=email_do_administrador
ADMIN_PASSWORD=troque_esta_senha_antes_de_publicar
ALLOWED_ORIGINS=https://app.example.com
SMTP_USERNAME=sua-conta@gmail.com
SMTP_PASSWORD=senha_de_app_do_gmail_sem_espacos
REDIS_URL=
TRUSTED_PROXY_HOPS=0
```

Substitua todos os exemplos. Ajuste `AUTH_COOKIE_SAMESITE` e
`TRUSTED_PROXY_HOPS` conforme os cuidados descritos acima. Instale apenas
`requirements.txt` em producao; `requirements-dev.txt` e destinado a testes.
No Gmail, a senha SMTP deve ser uma senha de app, nunca a senha normal da conta.

Comando de inicializacao:

```bash
python main.py
```

## Cuidados antes de subir para GitHub

Nao envie:

```text
.env
.venv/
__pycache__/
*.db
*.sqlite
*.sqlite3
```

Esses arquivos ja estao cobertos pelo `.gitignore`.

## Observacoes para o TCC

Este backend representa a camada de regras de negocio do sistema. Ele demonstra autenticacao, controle de permissao, persistencia via ORM, separacao entre rotas e servicos, migracoes de banco, indicadores operacionais e adequacao ao contexto da saude publica sem entrar no dominio de prontuario ou informacao clinica sensivel.

## Notificacoes por WhatsApp

O backend possui uma fila duravel para notificacoes de chamados usando Redis
Streams e um worker separado. O provedor externo previsto e a Evolution API
com uma instancia WhatsApp no modo Baileys. Nesta primeira versao o fluxo e
somente de saida: o sistema envia avisos, mas nao interpreta respostas pelo
WhatsApp.

Regras de destinatarios:

- abertura de chamado: tecnicos ativos e inscritos;
- reabertura, comentario e mudanca de status: usuario dono e tecnico vinculado;
- administradores: nao recebem a caixa comum, mas consultam os eventos em rota administrativa;
- o backend decide os destinatarios e repete a autorizacao ao abrir o chamado.

O processo HTTP grava o chamado, o evento e a entrega pendente no PostgreSQL.
O worker publica a entrega no Redis e chama a Evolution API. Falhas externas
geram novas tentativas limitadas, sem desfazer a operacao do chamado.

Variaveis adicionais na hospedagem:

```text
REDIS_URL=redis://...
WHATSAPP_ENABLED=true
EVOLUTION_API_URL=https://...
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=helpwebhealth
EVOLUTION_WEBHOOK_SECRET=...
WHATSAPP_FRONTEND_BASE_URL=https://app.example.com
```

Quando `WHATSAPP_ENABLED=true`, as cinco variaveis da Evolution acima e o
`REDIS_URL` sao obrigatorios. `EVOLUTION_WEBHOOK_SECRET` deve ser um segredo
aleatorio configurado tambem no webhook do provedor; ele nunca deve ser
colocado no frontend, em mensagens ou em logs.

Comando do worker, em um segundo servico da hospedagem:

```bash
python -m app.workers.whatsapp_worker
```

O webhook `POST /api/v1/webhooks/evolution` serve apenas para atualizar o
status de entrega e exige `EVOLUTION_WEBHOOK_SECRET`. Ele nao habilita respostas
ou comandos recebidos pelo WhatsApp.

## Busca e paginação

O rate limit local usa Token Bucket por escopo, IP e identidade da sessao. A
capacidade inicial permite pequenos picos e os tokens sao repostos ao longo do
tempo, sem depender de Redis. O dicionario local possui limite de chaves e
remove entradas ociosas ou antigas para nao crescer indefinidamente. Redis
continua opcional para uma futura execucao com varias instancias.

As respostas tambem informam `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset` e, quando bloqueadas, `Retry-After`.

`GET /api/v1/tickets/` aceita o parametro opcional `search` para localizar um
chamado pelo numero do codigo, titulo ou descricao. A API aplica primeiro o
escopo de visibilidade do usuario e somente depois executa a busca, evitando
que um usuario descubra chamados de outra pessoa.

As listagens usam `limit + 1` para informar `has_more` sem executar uma
contagem total a cada pesquisa ou troca de pagina. O campo `total` e opcional e
so e calculado quando uma tela de resumo solicita explicitamente
`include_total=true`. Isso reduz custo no banco e evita acumular registros no
frontend; a interface descarta a pagina anterior antes de renderizar a nova.

`GET /api/v1/admin/users` e exclusivo para administradores e aceita `search`
por inicio do nome, `role`, `is_active`, `order_by`, `direction`, `skip` e
`limit`. A ordenacao tambem e validada pela API, sem aceitar nomes de colunas
arbitrarios. A resposta possui
`items`, `total` opcional, `skip`, `limit` e `has_more`; nenhuma dessas
listagens carrega todos os registros em memoria. Os limites da API tambem
impedem paginas excessivamente grandes. A migration
`g7h8i9j0k1l2_search_performance_indexes` cria os indices usados pela pesquisa
de nomes e pela fila de chamados excluidos, incluindo o indice por
`lower(name)` no PostgreSQL.
