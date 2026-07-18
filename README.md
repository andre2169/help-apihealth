# HelpWeb Health API

Backend do **HelpWeb Health**, uma API REST desenvolvida com FastAPI para gerenciamento de chamados de TI em instituicoes de saude publica, como hospitais, clinicas, laboratorios, UPAs e setores administrativos ligados ao atendimento.

O sistema foi pensado para melhorar a comunicacao entre funcionarios e equipe de tecnologia, especialmente em ambientes onde falhas de infraestrutura podem impactar o atendimento: computadores, impressoras, rede Wi-Fi, sistemas internos, leitores de codigo de barras, coletores, telefonia e outros equipamentos.

Importante: este projeto nao e um prontuario eletronico e nao deve armazenar dados de pacientes. O foco e suporte tecnico, infraestrutura de TI e organizacao dos atendimentos.

## Objetivo

A API centraliza o ciclo de vida dos chamados:

- cadastro e autenticacao de usuarios;
- perfil de usuario com telefone, funcao, setor, unidade e preferencia de notificacao;
- alteracao de email e senha com codigo temporario de verificacao;
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
- Autenticacao JWT.
- Criptografia de senha com Passlib/Bcrypt.
- Troca de senha e email protegida por codigo temporario enviado por email.
- Logout com revogacao do JWT atual por `jti`.
- Rate limit global em memoria por IP + usuario/token, alem do bloqueio especifico de falhas no login.
- Headers de seguranca contra clickjacking e exposicao indevida de respostas.
- Swagger/OpenAPI desligado por padrao em producao.
- Health check publico simples, sem expor diagnostico do banco por padrao.
- Controle de permissao por perfil.
- SQLAlchemy ORM para facilitar migracao futura de banco.
- Alembic para versionamento do schema.
- SQLite para desenvolvimento, testes e deploy simples.
- Estrutura preparada para migrar futuramente para PostgreSQL ou MySQL.
- Chamados com setor, categoria, equipamento, codigo de patrimonio, impacto operacional e SLA.
- Foto opcional do problema no chamado.
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
  scripts/            Seeds e comandos auxiliares
  main.py             Entrada da aplicacao
  requirements.txt    Dependencias Python
  .env.example        Exemplo de variaveis de ambiente
```

## Variaveis de ambiente

Crie um arquivo `.env` na raiz da API usando `.env.example` como base:

```env
DATABASE_URL=sqlite:///./helphealth.db
SECRET_KEY=exemplo_troque_por_uma_chave_longa_e_secreta
ADMIN_EMAIL=admin.exemplo@helpwebhealth.local
ADMIN_PASSWORD=troque_esta_senha_antes_de_publicar
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ENABLE_API_DOCS=false
ENABLE_DB_HEALTH_ENDPOINT=false
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
MAIL_FROM=
MAIL_FROM_NAME=HelpWeb Health
REPLY_TO_EMAIL=
EMAIL_CODE_EXPIRE_MINUTES=15
VERIFICATION_RESEND_COOLDOWN_SECONDS=300
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_MAX_REQUESTS=240
RATE_LIMIT_SENSITIVE_MAX_REQUESTS=40
```

Descricao:

- `DATABASE_URL`: endereco do banco. Para SQLite local, use `sqlite:///./helphealth.db`.
- `SECRET_KEY`: chave usada para assinar tokens JWT. Em producao, use uma chave longa e secreta.
- `ADMIN_EMAIL`: e-mail inicial do administrador criado automaticamente.
- `ADMIN_PASSWORD`: senha inicial do administrador.
- `ALLOWED_ORIGINS`: dominios autorizados a chamar a API pelo navegador. Use a URL exata, sem barra final, e nunca use `*` em producao.
- `ENABLE_API_DOCS`: libera `/docs`, `/redoc` e `/openapi.json`. Use `true` apenas em desenvolvimento local.
- `ENABLE_DB_HEALTH_ENDPOINT`: libera `/health/db`. Em producao, mantenha `false` e use apenas `/health` como rota publica.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` e `MAIL_FROM`: configuracao do servidor de email usado para enviar codigos de verificacao.
- `MAIL_FROM_NAME`: nome exibido como remetente do email.
- `REPLY_TO_EMAIL`: email opcional para resposta/suporte. Pode ficar vazio.
- `EMAIL_CODE_EXPIRE_MINUTES`: tempo de validade dos codigos temporarios.
- `VERIFICATION_RESEND_COOLDOWN_SECONDS`: intervalo minimo para reenviar codigo de email/senha. O padrao de producao e 300 segundos.
- `RATE_LIMIT_WINDOW_SECONDS`: janela, em segundos, usada no rate limit global.
- `RATE_LIMIT_MAX_REQUESTS`: maximo de requisicoes gerais por IP + usuario/token dentro da janela.
- `RATE_LIMIT_SENSITIVE_MAX_REQUESTS`: maximo para rotas sensiveis, como auth, cadastro, admin e alteracoes.

Nunca suba o arquivo `.env` para o GitHub. Ele pode conter senhas, chaves e URLs privadas.

Se o SMTP nao estiver configurado, a API ainda gera o codigo e mostra nos logs. Isso facilita teste local, mas em producao o ideal e configurar um email real.

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

O projeto usa Alembic. Ao iniciar pelo `main.py`, as migracoes sao aplicadas automaticamente.

Para aplicar manualmente:

```bash
alembic upgrade head
```

## Seguranca aplicada

- Tokens JWT trafegam pelo header `Authorization: Bearer`.
- Cada JWT possui `jti`; ao fazer logout, o token atual entra na tabela `token_blocklist` ate expirar.
- Endpoints autenticados rejeitam tokens expirados, sem `jti` ou revogados.
- Login usa mensagem generica para reduzir enumeracao de usuario.
- Cadastro publico tambem evita confirmar diretamente se um email ja existe.
- Listagens usam respostas resumidas para nao trafegar imagem/base64 ou descricao completa sem necessidade.
- Timeline de chamados nao expõe email do autor, apenas dados minimos para identificar o registro.
- Rotas usam ORM SQLAlchemy e enums/whitelists para filtros e ordenacao, evitando SQL dinamico.
- CORS usa lista fixa de origens em `ALLOWED_ORIGINS`; em producao, evite `*`.
- `/docs`, `/redoc` e `/openapi.json` ficam desabilitados quando `ENABLE_API_DOCS=false`.
- `/health/db` fica desabilitado quando `ENABLE_DB_HEALTH_ENDPOINT=false`; `/health` continua disponivel para a hospedagem.

## Seeds para demonstracao

Para criar usuarios e chamados de exemplo:

```bash
python -m scripts.seed_users
python -m scripts.seed_tickets
```

Os dados simulam cenarios de suporte tecnico em saude publica, como UTI, recepcao, laboratorio, farmacia, pronto atendimento, equipamentos de impressao, rede e sistemas internos.

## Deploy na Shard

Configure as variaveis de ambiente pelo painel da Shard:

```env
DATABASE_URL=sqlite:///./helphealth.db
SECRET_KEY=gere_uma_chave_longa_e_secreta
ADMIN_EMAIL=email_do_administrador
ADMIN_PASSWORD=senha_inicial_forte_do_administrador
ALLOWED_ORIGINS=https://url-do-seu-frontend.shardweb.app
ENABLE_API_DOCS=false
ENABLE_DB_HEALTH_ENDPOINT=false
SMTP_HOST=smtp.seu-provedor.com
SMTP_PORT=587
SMTP_USERNAME=usuario_smtp
SMTP_PASSWORD=senha_smtp
SMTP_USE_TLS=true
MAIL_FROM=remetente_verificado@seudominio.com
MAIL_FROM_NAME=HelpWeb Health
REPLY_TO_EMAIL=
VERIFICATION_RESEND_COOLDOWN_SECONDS=300
```

No Brevo, `MAIL_FROM` precisa ser um remetente verificado ou pertencer a um dominio autenticado. Se o SMTP aceitar mas o email nao chegar, confira os logs transacionais da Brevo para ver se o evento ficou como `Delivered`, `Blocked`, `Deferred`, `Soft bounce` ou `Hard bounce`.

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
