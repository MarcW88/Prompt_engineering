# Référence Sources par Secteur

Ce document liste les sources **réutilisables** par type de client/secteur.
Le dev peut s'en servir pour pré-configurer les sources selon le secteur du client.

---

## 🏃 Sport / Équipement (Decathlon, Intersport...)

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/running, r/cycling, r/Fitness, r/CampingGear | Multi-sport |
| Randonner-léger | randonner-leger.org/forum | Rando, trek, outdoor |
| Skipass | skipass.com/forums | Ski, montagne |
| Velotaf | forum.velotaf.com | Vélo urbain |
| Hardware.fr Sports | forum.hardware.fr/hfr/Discussions/Sports | Généraliste sport |
| Jogging-Plus | jogging-plus.com/forum | Running |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | trustpilot.com/review/{domain} |
| Google Reviews | Via Places API |

---

## 💻 Tech / SaaS

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/software, r/SaaS, r/webdev, r/sysadmin | Tech généraliste |
| Hacker News | news.ycombinator.com | Startups, tech |
| Stack Overflow | stackoverflow.com | Dev, technique |
| ProductHunt | producthunt.com/discussions | Nouveaux produits |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| G2 | g2.com/products/{product}/reviews |
| Capterra | capterra.com/p/{id}/{product}/reviews |
| Trustpilot | trustpilot.com/review/{domain} |

---

## 🏠 Immobilier

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france, r/vosfinances | Immobilier FR |
| Forum Construire | forumconstruire.com | Construction, rénovation |
| Hardware.fr Immo | forum.hardware.fr/hfr/Discussions/Immobilier | Achat, location |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | trustpilot.com/review/{domain} |
| Google Reviews | Agences locales |
| Avis Vérifiés | avis-verifies.com |

---

## 🏦 Finance / Banque

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/vosfinances, r/FranceFIRE | Finance perso FR |
| Forum Bourso | boursorama.com/forum | Bourse, épargne |
| Devenir Rentier | devenir-rentier.fr/forum | Investissement |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | trustpilot.com/review/{domain} |
| Google Reviews | Agences bancaires |
| Selectra | selectra.info (comparatifs) |

---

## 📱 Télécom / Mobile

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france, r/French | Télécom FR |
| Forum Les Mobiles | lesmobiles.com/forum | Mobile |
| Univers Freebox | universfreebox.com/forum | FAI |
| LaFibre.info | lafibre.info/forum | Internet, fibre |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | trustpilot.com/review/{domain} |
| Google Reviews | Boutiques opérateurs |

---

## 🛒 E-commerce / Retail

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france, r/Frugal | Shopping FR |
| Dealabs | dealabs.com/discussions | Bons plans, avis |
| Hardware.fr | forum.hardware.fr | Tech, achats |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | trustpilot.com/review/{domain} |
| Avis Vérifiés | avis-verifies.com |
| Google Reviews | Magasins |

---

## 🏥 Santé / Bien-être

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france | Santé FR |
| Doctissimo | forum.doctissimo.fr | Santé généraliste |
| Aufeminin | forum.aufeminin.com | Santé femmes |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Google Reviews | Établissements santé |
| Trustpilot | Services santé en ligne |

---

## 🎓 Éducation / Formation

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france, r/etudiant | Études FR |
| Studyrama | forums.studyrama.com | Orientation |
| L'Étudiant | forums.letudiant.fr | Études supérieures |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Google Reviews | Écoles, centres formation |
| Trustpilot | Plateformes e-learning |

---

## 🚗 Automobile

### Forums
| Plateforme | URL | Thématiques |
|------------|-----|-------------|
| Reddit | r/france, r/Automobile | Auto FR |
| Forum Auto | forum-auto.com | Généraliste auto |
| Automobile Propre | forums.automobile-propre.com | Électrique |
| Caradisiac | forum.caradisiac.com | Multi-marques |

### Avis
| Plateforme | Pattern URL |
|------------|-------------|
| Trustpilot | Concessionnaires, services |
| Google Reviews | Garages, concessions |

---

## 🔧 Pattern de recherche universel

Pour **n'importe quel secteur**, ces patterns fonctionnent :

### Google Site Search
```
site:reddit.com "{marque}" "{thème}"
site:trustpilot.com/review "{marque}"
"{marque}" avis forum
"{marque}" problème
"{marque}" vs "{concurrent}"
```

### Reddit Search
```
subreddit:france "{marque}"
"{thème}" recommendation
"{marque}" review
```

### Trustpilot
```
https://fr.trustpilot.com/review/www.{domain}
```

---

## ⚠️ Notes techniques

### Anti-bot à prévoir
| Plateforme | Niveau | Contournement |
|------------|--------|---------------|
| Reddit | Faible | API officielle (PRAW) |
| Trustpilot | Moyen | Rotation headers, délais |
| Google Reviews | Élevé | Places API recommandée |
| Forums classiques | Faible | Scraping direct OK |

### Rate limits recommandés
| Source | Délai min entre requêtes |
|--------|--------------------------|
| Reddit API | 1 sec |
| Trustpilot | 3-5 sec |
| Google Search | 5-10 sec |
| Forums | 2 sec |
