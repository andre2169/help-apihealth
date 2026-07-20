# HelpWeb Health API

Backend do **HelpWeb Health**, uma API REST desenvolvida com FastAPI para gerenciamento de chamados de TI em instituicoes de saude publica, como hospitais, clinicas, laboratorios, UPAs e setores administrativos ligados ao atendimento.

O sistema foi pensado para melhorar a comunicacao entre funcionarios e equipe de tecnologia, especialmente em ambientes onde falhas de infraestrutura podem impactar o atendimento: computadores, impressoras, rede Wi-Fi, sistemas internos, leitores de codigo de barras, coletores, telefonia e outros equipamentos.

Importante: este projeto nao e um prontuario eletronico e nao deve armazenar dados de pacientes. O foco e suporte tecnico, infraestrutura de TI e organizacao dos atendimentos.

## Objetivo

A API centraliza o ciclo de vida dos chamados:

- cadastro e autenticacao de usuarios;
- perfil de usuario com telefone, funcao, setor, unidade e preferencia de notificacao;
- alteracao de email e senha com codigo temporario de verificacao;
- recuperacao de conta por codigo enviado ao email cadastrado;
- abertura de chamados por funcionarios;
- classificacao por setor, categoria, equipamento, patrimonio e impacto operacional;
- acompanhamento por status;
- atribuicao e resolucao por tecnicos;
- comentarios e linha do tempo;
- controle de perfis de acesso;
- indicadores para dashboard e relatorios filtrados.

Essa organizacao ajuda a reduzir perda de informacao, ligaÃ§Ãµes informais sem registro e dificuldade de priorizacao em setores sensiveis da saude publica.

## Perfis de usuario

O sistema trabalha com tres perfis:

- `user`: funcionario comum. Pode abrir chamados, acompanhar os proprios chamados, comentar, fechar ou reabrir quando permitido.
- `technician`: tecnico de TI. Pode visualizar chamados operacionais, assumir atendimentos, resolver chamados e acessar indicadores.
- `admin`: administrador. Pode gerenciar usuarios, visualizar indicadores e executar acoes administrativas.

Endpoints de dashboard e relatorios sao protegidos para `technician` e `admin`, evitando que usuarios comuns acessem dados operacionais que nao fazem parte do fluxo deles.

## Principais recursos

- API REST com FastAPI.
- Regras sensiveis centralizadas no backend: permissao, SLA, mudanca de status, filtros, limites de upload, verificacao de email, rate limit e calculos de relatorio.
- Autenticacao JWT com PyJWT.
- Criptografia de senha com Passlib/Bcrypt.
- Troca de senha e email protegida por codigo temporario enviado por email.
- Recuperacao de conta com resposta publica generica para reduzir enumeracao de usuarios.
- Logout com revogacao do JWT atual por `jti`.
- Rate limit global em memoria por IP + usuario/token, alem do bloqueio especifico de falhas no login por IP+conta e por conta.
- Headers de seguranca contra clickjacking e exposicao indevida de respostas.
- Logs de SMTP mascaram o email de destino.
- Logs podem ser emitidos em texto simples ou JSON por `LOG_FORMAT`.
- Tentativas de codigo invalido/expirado ficam registradas para auditoria sem salvar o codigo digitado.
- Headers de proxy so sao usados para identificar IP quando `TRUSTED_PROXY_HOPS` e configurado explicitamente.
- Swagger/OpenAPI desligado por padrao em producao e com protecao opcional por usuario/senha quando habilitado.
- Health check publico simples, sem expor diagnostico do banco por padrao.
- Controle de permissao por perfil.
- SQLAlchemy ORM para facilitar migracao futura de banco.
- Alembic para versionamento do schema.
- SQLite para desenvolvimento, testes e deploy simples em instancia unica.
- Lock de inicializacao para reduzir corrida entre migracoes/admin inicial quando mais de um processo sobe ao mesmo tempo.
- Suporte direto a SQLite no desenvolvimento e PostgreSQL no deploy.
- Pool de conexoes configuravel para reduzir latencia com PostgreSQL.
- Chamados com setor, categoria, equipamento, codigo de patrimonio, impacto operacional e SLA.
- Ate 3 fotos opcionais do problema no chamado, recebidas ja compactadas pelo frontend e validadas novamente no backend.
- Foto de perfil do usuario.
- Timeline de eventos e comentarios.
- Relatorios por periodo, status, prioridade, setor, categoria, equipamento, impacto, SLA, idade da fila, volume diario, solicitantes recorrentes e reaberturas.

## Estrutura principal

```text
helphealth-api/
  app/
    api/              Rotas da API
    core/             Configuracoes, autenticacao e permissoes
    db/               Sessao do banco e modelos SQLAlchemy
    schemas/          Schemas Pydantic
    services/         Regras de negocio
  alembic/            Migracoes do banco
  main.py             Entrada da aplicacao
  requirements.txt    Dependencias Python
  requirements-postgres.txt Atalho compativel para instalacao das dependencias
  tools/             Utilitarios locais, incluindo migracao SQLite -> PostgreSQL
  .env.example        Exemplo de variaveis de ambiente
```

## Variaveis de ambiente

Crie um arquivo `.env` na raiz da API usando `.env.example` como base:

```env
DATABASE_URL=sqlite:///./helphealth.db
# Para PostgreSQL na hospedagem:
# DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
SECRET_KEY=coloque_uma_chave_aleatoria_real_com_32_ou_mais_caracteres
AUTH_COOKIE_NAME=helpwebhealth_session
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
ADMIN_EMAIL=admin.exemplo@helpwebhealth.local
ADMIN_PASSWORD=troque_por_uma_senha_forte_com_12_ou_mais_caracteres
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ENABLE_API_DOCS=false
ENABLE_DB_HEALTH_ENDPOINT=false
API_DOCS_USERNAME=admin
API_DOCS_PASSWORD=
LOG_LEVEL=INFO
LOG_FORMAT=text
ALLOW_LOG_VERIFICATION_CODES=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=suporte.helpwebhealth@gmail.com
SMTP_PASSWORD=senha_de_app_do_gmail_sem_espacos
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=30
MAIL_FROM=suporte.helpwebhealth@gmail.com
MAIL_FROM_NAME=HelpWeb Health
REPLY_TO_EMAIL=suporte.helpwebhealth@gmail.com
EMAIL_CODE_EXPIRE_MINUTES=15
VERIFICATION_RESEND_COOLDOWN_SECONDS=300
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_MAX_REQUESTS=240
RATE_LIMIT_SENSITIVE_MAX_REQUESTS=40
TRUSTED_PROXY_HOPS=0
RUN_MIGRATIONS_ON_STARTUP=true
STARTUP_LOCK_PATH=
STARTUP_LOCK_TIMEOUT_SECONDS=120
STARTUP_LOCK_STALE_SECONDS=300
```

Descricao:

- `DATABASE_URL`: endereco do banco. Para SQLite local, use `sqlite:///./helphealth.db`. Para PostgreSQL, use a URL fornecida pela Shard, no formato `postgresql://usuario:senha@host:porta/banco?sslmode=require`. Se a Shard entregar `postgres://` ou `?ssl=true`, a aplicacao normaliza automaticamente para `postgresql://` com `sslmode=require`.
- `DB_POOL_SIZE`: quantidade de conexoes permanentes mantidas no pool quando o banco nao for SQLite.
- `DB_MAX_OVERFLOW`: conexoes extras permitidas quando o pool estiver cheio.
- `DB_POOL_TIMEOUT_SECONDS`: tempo maximo aguardando uma conexao livre do pool.
- `DB_POOL_RECYCLE_SECONDS`: tempo para reciclar conexoes antigas e evitar conexao morta em banco gerenciado.
- `SECRET_KEY`: chave usada para assinar tokens JWT. A API recusa iniciar com chave de exemplo ou menor que 32 caracteres.
- `AUTH_COOKIE_NAME`: nome do cookie HttpOnly usado para sessao.
- `AUTH_COOKIE_SECURE`: use `false` somente em teste local HTTP. Em producao HTTPS, use `true`.
- `AUTH_COOKIE_SAMESITE`: use `lax` em teste local. Se frontend e API ficarem em subdominios diferentes na Shard, use `none` junto com `AUTH_COOKIE_SECURE=true`.
- `AUTH_COOKIE_DOMAIN`: normalmente fica vazio. Configure dominio compartilhado apenas se souber exatamente o dominio-base aceito pelo navegador.
- `ADMIN_EMAIL`: e-mail inicial do administrador criado automaticamente.
- `ADMIN_PASSWORD`: senha inicial do administrador. A API recusa iniciar com senha de exemplo ou menor que 12 caracteres.
- `ALLOWED_ORIGINS`: dominios autorizados a chamar a API pelo navegador. Use a URL exata, sem barra final, e nunca use `*` em producao.
- `ENABLE_API_DOCS`: libera `/docs`, `/redoc` e `/openapi.json`. Use `true` apenas em desenvolvimento local.
- `ENABLE_DB_HEALTH_ENDPOINT`: libera `/health/db`. Em producao, mantenha `false` e use apenas `/health` como rota publica.
- `API_DOCS_USERNAME` e `API_DOCS_PASSWORD`: protegem a documentacao por autenticacao basica quando `ENABLE_API_DOCS=true`. A API recusa iniciar docs habilitada sem senha.
- `LOG_LEVEL`: nivel minimo dos logs, como `INFO`, `WARNING` ou `ERROR`.
- `LOG_FORMAT`: use `text` para leitura simples ou `json` para monitoramento externo.
- `ALLOW_LOG_VERIFICATION_CODES`: se `true`, permite exibir codigos de verificacao nos logs para teste local. Em producao, mantenha `false`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`, `SMTP_TIMEOUT_SECONDS` e `MAIL_FROM`: configuracao do servidor de email usado para enviar codigos de verificacao. Para Gmail, use `smtp.gmail.com`, porta `587`, `SMTP_USE_TLS=true` e senha de app.
- `MAIL_FROM_NAME`: nome exibido como remetente do email.
- `REPLY_TO_EMAIL`: email opcional para resposta/suporte. Pode ficar vazio.
- `EMAIL_CODE_EXPIRE_MINUTES`: tempo de validade dos codigos temporarios.
- `VERIFICATION_RESEND_COOLDOWN_SECONDS`: intervalo minimo para reenviar codigo de email/senha. O padrao de producao e 300 segundos.
- `RATE_LIMIT_WINDOW_SECONDS`: janela, em segundos, usada no rate limit global.
- `RATE_LIMIT_MAX_REQUESTS`: maximo de requisicoes gerais por IP + usuario/token dentro da janela.
- `RATE_LIMIT_SENSITIVE_MAX_REQUESTS`: maximo para rotas sensiveis, como auth, cadastro, admin e alteracoes.
- `TRUSTED_PROXY_HOPS`: quantidade de proxies confiaveis usados para ler `X-Forwarded-For`. O padrao `0` ignora headers enviados pelo cliente. Use `1` somente se a hospedagem confirmar que sobrescreve ou concatena esse header corretamente.
- `RUN_MIGRATIONS_ON_STARTUP`: controla se `main.py` aplica migracoes automaticamente ao iniciar. No deploy simples da Shard, mantenha `true`.
- `STARTUP_LOCK_PATH`: caminho opcional do arquivo de lock de inicializacao. Se vazio e o banco for SQLite, o lock fica ao lado do `.db`.
- `STARTUP_LOCK_TIMEOUT_SECONDS`: tempo maximo aguardando outro processo terminar migracao/admin inicial.
- `STARTUP_LOCK_STALE_SECONDS`: idade minima para considerar um lock abandonado.

Nunca suba o arquivo `.env` para o GitHub. Ele pode conter senhas, chaves e URLs privadas.

Se o SMTP nao estiver configurado, a API gera o codigo, mas nao exibe o codigo nos logs por padrao. Para teste local, e possivel ativar `ALLOW_LOG_VERIFICATION_CODES=true`. Em producao, configure um SMTP real e mantenha essa opcao desligada.

### SMTP com Gmail

Para usar a conta `suporte.helpwebhealth@gmail.com`, ative a verificacao em duas etapas na conta Google e gere uma senha de app. No painel da Shard, configure:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=suporte.helpwebhealth@gmail.com
SMTP_PASSWORD=sua_senha_de_app_do_google_sem_espacos
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=30
MAIL_FROM=suporte.helpwebhealth@gmail.com
MAIL_FROM_NAME=HelpWeb Health
REPLY_TO_EMAIL=suporte.helpwebhealth@gmail.com
```

Use a senha de app de 16 caracteres, nao a senha normal da conta Google. Se voce copiar a senha com espacos, a API remove os espacos automaticamente quando `SMTP_HOST=smtp.gmail.com`, mas o ideal e salvar sem espacos no painel.

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
pip install -r requirements.txt
```

Crie o arquivo `.env` com base no `.env.example`.

Execute a API:

```bash
python main.py
```

A API ficara disponivel em:

```text
http://127.0.0.1:8000
```

Documentacao interativa, se `ENABLE_API_DOCS=true` no `.env`:

```text
http://127.0.0.1:8000/docs
```

## Migracoes do banco

O projeto usa Alembic. Ao iniciar pelo `main.py`, as migracoes sao aplicadas automaticamente quando `RUN_MIGRATIONS_ON_STARTUP=true`.

No deploy simples com SQLite, `main.py` usa um lock de arquivo antes de rodar migracoes e criar o admin inicial. Isso reduz risco de corrida se a hospedagem iniciar mais de um processo ao mesmo tempo. Em um deploy mais maduro, especialmente com PostgreSQL e CI/CD, prefira rodar `alembic upgrade head` como etapa separada do deploy e usar `RUN_MIGRATIONS_ON_STARTUP=false`.

As migrations atuais foram revisadas para funcionar tanto em SQLite quanto em PostgreSQL, incluindo campos booleanos usados na verificacao de email.

Para aplicar manualmente:

```bash
alembic upgrade head
```

### Usando PostgreSQL na Shard

No painel da API na Shard, troque apenas a variavel `DATABASE_URL` pela URL do PostgreSQL criado na plataforma. Exemplo:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
```

Mantenha tambem:

```env
RUN_MIGRATIONS_ON_STARTUP=true
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
```

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
- Cadastro publico tambem evita confirmar diretamente se um email ja existe.
- Listagens usam respostas resumidas para nao trafegar imagem/base64 ou descricao completa sem necessidade.
- Timeline de chamados nao expõe email do autor, apenas dados minimos para identificar o registro.
- Rotas usam ORM SQLAlchemy e enums/whitelists para filtros e ordenacao, evitando SQL dinamico.
- CORS usa lista fixa de origens em `ALLOWED_ORIGINS`; em producao, evite `*`.
- Requisicoes `POST`, `PATCH`, `PUT` e `DELETE` vindas de `Origin` fora da lista autorizada sao bloqueadas tambem no middleware da API.
- IP de log/rate limit usa headers de proxy somente quando `TRUSTED_PROXY_HOPS` e habilitado.
- `/docs`, `/redoc` e `/openapi.json` ficam desabilitados quando `ENABLE_API_DOCS=false`.
- Quando `ENABLE_API_DOCS=true`, a documentacao precisa de `API_DOCS_USERNAME` e `API_DOCS_PASSWORD`; sem senha, a API nao inicia.
- `/health/db` fica desabilitado quando `ENABLE_DB_HEALTH_ENDPOINT=false`; `/health` continua disponivel para a hospedagem.
- Uploads em Data URL sao validados no backend por tipo permitido, base64 valido, assinatura real de imagem e tamanho. O limite foi ajustado para aceitar fotos de celular compactadas sem permitir imagens brutas excessivas no banco SQLite.
- Codigos temporarios de email/senha sao armazenados apenas como HMAC, nao em texto puro.
- O backend nao grava senhas, tokens JWT, codigo digitado ou email completo em logs.
- Em 19/07/2026, as dependencias de producao do `requirements.txt` foram atualizadas e auditadas com `pip-audit`, sem vulnerabilidades conhecidas no resultado.
- O projeto pode usar SQLite em deploy simples, mas PostgreSQL e recomendado para ambiente real por oferecer melhor concorrencia, backup, isolamento e recursos de seguranca do banco gerenciado.
- O arquivo SQLite nao e criptografado integralmente por padrao; para dados reais, prefira PostgreSQL gerenciado com criptografia em repouso, backup e controle de acesso.
- A listagem administrativa de usuarios retorna email mascarado e nao envia foto/base64 em massa.
- Novos cadastros precisam confirmar email antes de abrir chamados.
- Eventos sensiveis sao registrados em trilha de auditoria persistente (`audit_events`) sem gravar senha, token, codigo temporario ou email completo.
- Redis nao e obrigatorio nesta versao. Ele pode ser adotado futuramente para rate limit distribuido, cache, fila de emails e melhor suporte a varias instancias da API.
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

## Logs e privacidade

Os logs evitam expor dados sensiveis desnecessarios. Emails de login e envio SMTP sao mascarados, por exemplo `an***9@gmail.com`. Por seguranca, a API ignora `X-Forwarded-For`, `X-Real-IP` e `CF-Connecting-IP` por padrao. Configure `TRUSTED_PROXY_HOPS=1` apenas depois de confirmar o comportamento do proxy da hospedagem.

## Admin inicial

O administrador inicial e criado automaticamente na primeira execucao usando `ADMIN_EMAIL` e `ADMIN_PASSWORD`. Scripts de seed de usuarios/chamados de demonstracao foram removidos para evitar credenciais fixas em codigo versionado.

## Deploy na Shard

Configure as variaveis de ambiente pelo painel da Shard:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco?sslmode=require
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
SECRET_KEY=gere_uma_chave_aleatoria_com_32_caracteres_ou_mais
AUTH_COOKIE_NAME=helpwebhealth_session
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=none
AUTH_COOKIE_DOMAIN=
ADMIN_EMAIL=email_do_administrador
ADMIN_PASSWORD=senha_inicial_forte_com_12_ou_mais_caracteres
ALLOWED_ORIGINS=https://url-do-seu-frontend.shardweb.app
ENABLE_API_DOCS=false
ENABLE_DB_HEALTH_ENDPOINT=false
API_DOCS_USERNAME=admin
API_DOCS_PASSWORD=
LOG_LEVEL=INFO
LOG_FORMAT=text
ALLOW_LOG_VERIFICATION_CODES=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=suporte.helpwebhealth@gmail.com
SMTP_PASSWORD=senha_de_app_do_gmail_sem_espacos
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=30
MAIL_FROM=suporte.helpwebhealth@gmail.com
MAIL_FROM_NAME=HelpWeb Health
REPLY_TO_EMAIL=suporte.helpwebhealth@gmail.com
VERIFICATION_RESEND_COOLDOWN_SECONDS=300
TRUSTED_PROXY_HOPS=0
RUN_MIGRATIONS_ON_STARTUP=true
STARTUP_LOCK_TIMEOUT_SECONDS=120
STARTUP_LOCK_STALE_SECONDS=300
```

No Gmail, `SMTP_USERNAME` e `MAIL_FROM` devem usar o email completo da conta. A senha deve ser uma senha de app criada na conta Google, nunca a senha normal de login.

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
