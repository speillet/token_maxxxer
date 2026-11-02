# token_maxxxer

Orchestrateur local de tâches de développement, avec un fournisseur IA
configurable : **Claude via clé API**, **OpenAI via clé API**, puis
**GitHub Copilot via son SDK et un token GitHub autorisé**.

Le paquet Python, la commande et le dépôt portent le nom `token_maxxxer`.
Python 3.11+, macOS et Linux. [Roadmap](roadmap.md) · [Checkpoints et rollbacks](checkpoint.md).

## État actuel

| Fonction | État |
| --- | --- |
| Configuration Pydantic, modèles, import YAML et file SQLite | Disponible |
| Diagnostic, liste et simulation sans requête API | Disponible |
| Génération de texte Claude / OpenAI par API officielle | Disponible avec `query`, testée sur HTTP simulé |
| Stockage privé et résolution des références de credentials | Disponible |
| GitHub Copilot | Interface prévue ; adaptateur SDK à implémenter |
| Agent modifiant du code, worktrees, tests métier | À implémenter |
| Workflow LangGraph durable, planning et services | À implémenter |

`query` produit une réponse texte. Elle ne lit pas le dépôt, n'applique pas de
patch, ne lance pas de commande et ne marque aucune tâche comme réussie.
Les tests ne font aucun appel facturé et ne prouvent pas l'accès d'un compte réel.

## Installation et premiers contrôles

```bash
uv sync --locked
uv run token_maxxxer --help
uv run token_maxxxer --config examples/token_maxxxer.yaml doctor
uv run token_maxxxer --config examples/token_maxxxer.yaml tasks import examples/tasks.yaml
uv run token_maxxxer --config examples/token_maxxxer.yaml tasks list
uv run token_maxxxer --config examples/token_maxxxer.yaml run --dry-run
```

L'exemple autorise la racine de ce dépôt et utilise `var/token_maxxxer.sqlite`.
Adapter les chemins et tâches avant une utilisation réelle. Les chemins relatifs
sont résolus depuis leur fichier YAML ; sans `--config`, le fichier attendu est
`./token_maxxxer.yaml`. Les fichiers privés de configuration sont ignorés par Git.

`doctor` vérifie Git, les racines autorisées, les emplacements, le fournisseur et
la présence d'une clé ou référence. Il ne récupère pas le secret du Trousseau,
ne contacte aucune API et ne valide pas la clé auprès du fournisseur. Claude
Code et un abonnement Claude ne sont pas nécessaires au parcours API.

## Choisir le fournisseur

La configuration complète est dans [examples/token_maxxxer.yaml](examples/token_maxxxer.yaml).
Le modèle est obligatoire : aucun modèle ni fournisseur n'est substitué automatiquement.

```yaml
provider:
  name: claude
  model: claude-sonnet-5-5
  max_output_tokens: 4096
  timeout_seconds: 60

authentication:
  mode: api_key
  env_file: ../.env
```

Pour OpenAI, remplacer le bloc fournisseur par :

```yaml
provider:
  name: openai
  model: gpt-5.4-mini
  max_output_tokens: 4096
  timeout_seconds: 60
```

Les modèles d'exemple sont configurables ; vérifier leur accès dans le compte.
Une clé API utilise le compte API correspondant. Le plafond de sortie borne les
tokens demandés et ne garantit pas un montant exact de facturation.
Les adaptateurs n'effectuent aucune relance automatique et n'appellent pas un
second fournisseur en cas d'erreur.

## Credentials sans secret dans Git

Deux sources sont prises en charge pour le fournisseur sélectionné :

1. Une variable d'environnement du processus : `ANTHROPIC_API_KEY` pour Claude,
   `OPENAI_API_KEY` pour OpenAI.
2. Une référence au gestionnaire de credentials, dans l'environnement ou dans
   le `.env` local. Les références d'environnement passent avant celles du fichier.

```dotenv
TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF=keychain://token_maxxxer.claude.api/token_maxxxer
# TOKEN_MAXXXER_OPENAI_CREDENTIAL_REF=keychain://token_maxxxer.openai.api/token_maxxxer
```

Les services et comptes sont ceux des entrées du Trousseau macOS. Une référence
existante reste utilisable, même si son service conserve un ancien identifiant.
`query` récupère uniquement le credential du fournisseur sélectionné, au moment
de la requête. Sur Linux, fournir la clé dans l'environnement du processus ;
les références au Trousseau macOS ne sont pas disponibles.

Le lecteur de `.env` accepte uniquement les références connues, sans exécuter
le fichier, interpoler des valeurs ou modifier l'environnement global. Il refuse
les clés API en texte clair dans ce fichier. Conserver les permissions `0600`.
Seul [.env.example](.env.example), sans secret, est versionné. Une rotation de clé
se fait dans le gestionnaire de credentials ou l'environnement, jamais dans Git.

## Envoyer une consigne par API

Après avoir configuré une clé et un modèle, créer un fichier UTF-8 contenant la
consigne, puis lancer explicitement :

```bash
uv run token_maxxxer --config examples/token_maxxxer.yaml query --prompt-file consigne.txt
```

La commande envoie la consigne au fournisseur configuré ; elle peut donc consommer
son allocation API. `--prompt-file -` lit stdin, et `--json` restitue le résultat
normalisé, les tokens observés et les diagnostics expurgés. Les valeurs d'usage
absentes restent inconnues ; elles ne deviennent pas zéro. Les réponses tronquées,
refusées ou en erreur ne sont pas des réussites.

Pour vérifier la configuration sans requête réseau, utiliser `doctor` ou
`run --dry-run`. Ces commandes ainsi que `tasks list` ne créent pas de base et ne
modifient ni la file ni les dépôts.

## File de tâches

Les tâches doivent être explicites et provenir d'un YAML de confiance. Chaque
tâche indique un identifiant stable, une racine Git autorisée, une base, une
consigne, des critères d'acceptation et des commandes de vérification sous forme
de listes d'arguments. Voir [examples/tasks.yaml](examples/tasks.yaml).

Une priorité supérieure passe d'abord ; à égalité, l'ordre d'arrivée s'applique.
Un réimport identique ne duplique pas la tâche. Réutiliser un identifiant avec
une autre définition refuse le lot entier. Les sous-répertoires ne sont pas
implicitement autorisés par l'autorisation d'une racine.

Les commandes `run --once`, pause/reprise, rapports et services arrivent aux
jalons suivants. L'exécution future préparera un worktree par tâche, donnera aux
fournisseurs des outils explicitement autorisés et n'acceptera une réussite
qu'après vérification. Aucune tâche artificielle n'est créée pour consommer des tokens.

## Architecture

```text
src/token_maxxxer/
├── config.py, models.py       # configuration et données validées
├── credentials.py            # références privées, résolution à la demande
├── providers.py              # Provider, Claude Messages et OpenAI Responses
├── queue.py, storage.py       # import atomique et SQLite versionné
├── cli.py, doctor.py          # commandes utilisateur et diagnostic sans réseau
└── process.py, redaction.py   # processus bornés et diagnostics expurgés
```

LangGraph et LangChain Core sont installés pour le futur workflow déterministe.
Les checkpoints du graphe utiliseront une base distincte de la file applicative.
Le prototype Claude Code de la PR #2 reste testé comme intégration historique,
mais le parcours principal utilise les API. Son contrat est archivé dans
[docs/archive/claude-cli-contract.md](docs/archive/claude-cli-contract.md).

Copilot utilisera le même port `Provider`, avec un adaptateur propre à son SDK
et à son authentification GitHub. `provider.name: copilot` est reconnu mais
refusé à l'exécution tant que l'adaptateur n'est pas livré ; aucune URL privée
Copilot ni récupération implicite des credentials de `gh` n'est utilisée.
Contrats et sources officielles : [docs/providers.md](docs/providers.md).

## Développement et migration

```bash
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest -q
uv build --no-sources
```

Les tests utilisent des transports HTTP simulés, un faux CLI et des dépôts
 temporaires. La CI couvre Python 3.11/3.13 sur macOS et Linux.
Conventions : [CONTRIBUTING.md](CONTRIBUTING.md).

Depuis le prototype, mettre à jour les imports, la commande et la configuration
vers `token_maxxxer`, ajouter `provider` et passer `authentication.mode` à
`api_key`. Les variables de référence portent désormais le préfixe
`TOKEN_MAXXXER_`. Aucune donnée locale ni entrée de Trousseau n'est renommée ou
supprimée automatiquement. Pour conserver une ancienne base, garder son chemin
explicite dans `storage.database` ; l'identifiant et le schéma SQLite restent
compatibles. Sauvegarder les données séparément avant tout changement.
