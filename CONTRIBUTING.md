# Contribuer

Python 3.11 minimum, macOS et Linux. Installer les dépendances avec le lockfile :

```bash
uv sync --locked
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest -q
uv build --no-sources
```

## Conventions

- Garder le routage déterministe et les fournisseurs derrière l'interface
  `Provider`. Claude et OpenAI utilisent leurs API officielles ; Copilot sera
  raccordé via son SDK officiel et son authentification GitHub.
- Valider les entrées avec les modèles Pydantic. Refuser les champs inconnus et
  les chemins de dépôts qui ne figurent pas explicitement dans l'allowlist.
- Passer les commandes comme listes d'arguments, sans shell. Définir un timeout
  et une politique d'arrêt avant d'introduire un nouveau processus externe.
- Ne jamais lire les jetons OAuth ou inclure des valeurs d'authentification dans
  les logs. Les diagnostics ne doivent afficher que des métadonnées approuvées.
- Persister les timestamps en UTC avec fuseau ; garder le planning local en IANA.
- Garder `list`, `doctor` et `--dry-run` sans mutation de la file ou des dépôts.
- Séparer la base applicative des checkpoints LangGraph. Versionner les
  migrations et refuser une base inconnue ou plus récente.
- Tester les comportements, les échecs et les frontières de confiance modifiés.
  Utiliser des transports HTTP simulés, un faux CLI et des dépôts temporaires ;
  aucun test ne consomme une API réelle.
- Implémenter les modules au jalon où ils deviennent utiles ; ne pas ajouter
  d'interfaces vides ou de chemins d'exécution qui prétendent être disponibles.

## Livraisons et retour arrière

Créer une branche courte et des commits Conventional Commits, une responsabilité
par commit. Avant une PR, exécuter les contrôles ci-dessus et mettre à jour
`checkpoint.md`, les cases réellement couvertes de `roadmap.md` et les commandes
disponibles dans le README. Ne cocher une validation opérationnelle qu'avec une
  preuve réelle. Une source documentaire ou un transport simulé ne valide pas
  l'accès d'un compte réel. Une génération de texte réussie ne valide pas une tâche Git.

Une PR décrit le changement, ses preuves de validation, ses limites et son
retour arrière. Après publication, utiliser `git revert`, sans réécrire
l'historique partagé. Sauvegarder séparément les données et les worktrees avant
une évolution de schéma ; consulter [checkpoint.md](checkpoint.md).
