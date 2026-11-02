# Checkpoints — Claude Nightshift

Mis à jour le 2 novembre 2026. Ce fichier suit les livraisons du code ; il ne
remplace pas les checkpoints d'exécution LangGraph du futur jalon 4.

## État du projet

| Jalon | État | Preuves / suite |
| --- | --- | --- |
| 0 — Abonnement | Partiel | Contrat documentaire ; CLI absent de cette machine, validation du compte et appel réel à faire |
| 1 — Socle Python | Socle livré | Configuration, modèles, SQLite, CLI en lecture/simulation et tests locaux ; modules d'exécution aux jalons suivants |
| 2 — Exécuteur | En cours, hors ligne | Résultat normalisé, faux exécuteur et transport subprocess ; qualification réelle toujours ouverte |
| 3 à 7 | À faire | Suivre `roadmap.md` ; aucune exécution Claude réelle dans ce lot |

Le socle se développe hors ligne pendant que la validation opérationnelle du
jalon 0 reste ouverte. Le chemin d'exécution abonnement ne sera pas activé avant
cette validation. Aucune fixture synthétique ne vaut preuve d'un appel réel.

## Points de retour

| Repère | Révision | Contenu | Validation |
| --- | --- | --- | --- |
| CP-000 | `ad0992b` | README et roadmap d'origine | Arbre Git propre avant implémentation |
| CP-001 | `0fdce5a` | Contrat externe et protocole de suivi | Sources officielles relues, limites locales consignées |
| CP-002 | `26469a7` | Packaging verrouillé, YAML sûr, configuration et modèles | 31 tests ciblés configuration/modèles, Ruff et mypy |
| CP-003 | `dbcb978` | Migration SQLite initiale, import atomique, ordre priorité/arrivée et lecture seule | 9 tests de file : concurrence d'import, rollback de lot, autorisation et conservation des états |
| CP-004 | `9dcefaf` | Diagnostic sans inférence, import/liste, `run --dry-run` et JSON | 10 tests CLI ; 50 tests au total, paquet construit |
| CP-005 | `425075f` | CI Python 3.11/3.13, conventions et documentation des commandes disponibles | Actions épinglées par SHA ; 50 tests locaux sur les deux versions et smoke CLI en processus séparés |
| CP-006 | `e3f7f88` | Correction du constat P2 des revues Standards et Spec : chemins SQLite imbriqués et parent fichier refusés | 55 tests sur Python 3.11 ; correction confirmée par les deux revues |
| CP-007 | `ae1ecf7` | Socle Python documenté, point de départ du jalon 2 | Arbre propre à la reprise ; PR #1 ouverte |
| CP-008 | Commit `feat(runner): normalize terminal results and redact diagnostics` | Classification conservatrice du JSON terminal, usage inconnu et diagnostics expurgés | Fixtures synthétiques ; tests de résultats et de credentials factices |

## Livraison du socle

- Branche : `feat/python-foundation`.
- PR : [#1 — socle Python hors ligne](https://github.com/speillet/token_maxxxer/pull/1).
- Validation locale : 55 tests sous Python 3.11 ; les 50 tests du lot initial
  passaient aussi sous Python 3.13. Ruff, format, mypy strict, sdist et wheel
  validés. Import de LangGraph, LangChain Core et `SqliteSaver` vérifié.
- Smoke CLI en processus séparés : import, réimport, liste, simulation et
  diagnostic ; tâche toujours `pending`, état Git inchangé, stockage temporaire.
- Revue Standards : 1 constat P2, corrigé dans CP-006 et revérifié ; 0 ouvert.
- Revue Spec : 1 constat P2, corrigé dans CP-006 et revérifié ; 0 ouvert.
- CI distante : matrice macOS/Linux et Python 3.11/3.13 ; consulter les checks de
  la PR pour le résultat attaché à la dernière révision.

Chaque livraison ajoute ici son périmètre, ses vérifications et le nom du commit.
Pour retrouver son SHA : `git log --oneline --all`. Les commits portent une seule
responsabilité et utilisent Conventional Commits.

## Retour arrière

Pour inspecter un point sans toucher au travail courant :

```bash
git worktree add --detach ../nightshift-cp000 ad0992b
```

Pour annuler un commit publié, créer une branche puis un commit inverse avec
`git revert <sha>`, lancer les vérifications et ouvrir une PR. Annuler les commits
dépendants du plus récent au plus ancien. Conserver l'historique partagé.

Les données locales (`var/`, worktrees, rapports) sont exclues de Git : un revert
de code ne les restaure pas. Avant une migration future, arrêter le service et
effectuer une sauvegarde SQLite avec son API `backup` ; conserver aussi les
worktrees non validés. La migration initiale n'a pas de downgrade destructif.

## Prochaine reprise

1. Consulter les résultats CI de la PR du socle.
2. Installer/identifier le CLI officiel, vérifier la connexion abonnement et les
   crédits supplémentaires dans le compte, puis consigner un appel minimal.
3. Commencer le jalon 2 avec le faux exécuteur et les scénarios d'erreur.
