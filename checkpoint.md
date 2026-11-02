# Checkpoints — Claude Nightshift

Mis à jour le 2 novembre 2026. Ce fichier suit les livraisons du code ; il ne
remplace pas les checkpoints d'exécution LangGraph du futur jalon 4.

## État du projet

| Jalon | État | Preuves / suite |
| --- | --- | --- |
| 0 — Abonnement | Partiel | Contrat documentaire ; CLI absent de cette machine, validation du compte et appel réel à faire |
| 1 — Socle Python | En cours | Configuration, modèles, SQLite, CLI en lecture/simulation, tests et CI |
| 2 à 7 | À faire | Suivre `roadmap.md` ; aucune exécution Claude réelle dans ce lot |

Le socle se développe hors ligne pendant que la validation opérationnelle du
jalon 0 reste ouverte. Le chemin d'exécution abonnement ne sera pas activé avant
cette validation. Aucune fixture synthétique ne vaut preuve d'un appel réel.

## Points de retour

| Repère | Révision | Contenu | Validation |
| --- | --- | --- | --- |
| CP-000 | `ad0992b` | README et roadmap d'origine | Arbre Git propre avant implémentation |
| CP-001 | Commit `docs: record CLI contract and implementation checkpoints` | Contrat externe et protocole de suivi | Sources officielles relues, limites locales consignées |

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

1. Finir et valider le socle du jalon 1.
2. Installer/identifier le CLI officiel, vérifier la connexion abonnement et les
   crédits supplémentaires dans le compte, puis consigner un appel minimal.
3. Commencer le jalon 2 avec le faux exécuteur et les scénarios d'erreur.
