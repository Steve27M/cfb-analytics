# A Plain-English Guide to this Project

**No data background needed.** This guide explains what this project is, how it works, and how to
read its results — in everyday language, with the jargon spelled out as we go. If you've ever
watched a football game and wondered *"was that running back actually good, or just lucky?"*, this
is for you. (For the technical version, see [`README.md`](README.md).)

---

## 1. What is this, in one breath?

It's a **computer system that collects college-football data, cleans and organizes it, and then
uses math to answer two kinds of questions:**

1. **Was a team or player actually good?** (separating real skill from good luck)
2. **Who is likely to win a game?** (and how confident should we be?)

It's a *portfolio project* — something built to **demonstrate skill**, the way an architect shows a
model building. The football answers are real and interesting, but the deeper point is *how
carefully the whole thing is built.*

---

## 2. Where does the information come from?

All the numbers come from a free public service called **CollegeFootballData.com**. Think of it as a
giant online spreadsheet of everything that happened in college football — every game, every play,
every score. Our system politely asks it for the 2023 and 2024 seasons and saves a copy.

> The technical name for "a service you ask for data over the internet" is an **API**. You ask a
> question, it hands back data. We're careful to ask gently (there's a monthly limit) and we never
> re-download something we already have.

---

## 3. How the system works — the assembly-line idea

Raw data is messy, like vegetables straight from a farm: dirty, uneven, not ready to cook with. So
the project runs the data through an **assembly line**, where each station makes it a little more
useful. Data engineers call these stations **"bronze → silver → gold"** (like medal tiers).

| Station | Plain meaning | Kitchen analogy |
|---|---|---|
| **Bronze** | The raw data, saved exactly as it arrived, never edited. | Unwashed groceries in the crate |
| **Silver** | Cleaned and tidied: duplicates removed, names made consistent, obvious errors fixed. | Washed, peeled, chopped |
| **Gold** | Organized into neat tables ready to use, with quality-checks run on them. | Prepped ingredients in labeled bowls |
| **Models** | The math that turns tidy data into insight and predictions. | The actual cooking |
| **Dashboard** | Charts and tables that show the results to a human. | Plating and serving |

A single command runs the whole line from start to finish. If **any** station fails, the line stops
immediately — so you never get a half-cooked, misleading result.

### A quirk worth knowing: it speaks two languages

The project does its math in **both R and Python** — two popular programming languages for data.
Why both? Two reasons:

- Some tools are better in one language than the other, so we use each for what it's best at.
- **It's a built-in lie detector.** Every calculation is done *twice*, once in each language,
  completely separately. If the two answers don't match, the system **refuses to finish** and
  reports an error. It's like two accountants working in different rooms and comparing totals: if
  they disagree, someone made a mistake. (In this project, they agree on all 23 checks.)

---

## 4. The football ideas, explained simply

The project is built around one clever idea from the book it's based on: **"compared to what?"**

A raw stat like "gained 5 yards" doesn't tell you much on its own. Five yards on 3rd-and-20 is
useless; five yards on 3rd-and-2 wins the down. So instead of judging the *result*, we judge the
result **against what was expected in that exact situation.** Doing *better than expected*, over and
over, is what real skill looks like.

Here are the specific ideas you'll see:

- **Expected Points (EP) and EPA.** Every spot on the field is worth a certain number of points *on
  average* — being close to the other team's goal is worth a lot; being backed up near your own goal
  is worth almost nothing (or even *negative*, because you might get scored on). **EPA** = "Expected
  Points Added" = how much a single play *changed* your expected points. A great play adds points;
  a bad play subtracts them. This is the ruler we measure almost everything with.

- **RYOE — "Rushing Yards Over Expected."** Given the down, distance, and field position, how many
  yards would an *average* runner gain here? If a player consistently gains *more* than that, that's
  RYOE — a sign of a genuinely good runner (or a great offensive line).

- **CPOE — "Completion Percentage Over Expected."** Same idea for quarterbacks: given the situation,
  how likely was this pass to be caught? A QB who completes *harder* passes than expected has a
  positive CPOE.

- **Win probability.** Before a game, what's the chance the home team wins? Not a yes/no guess — a
  *percentage*, like a weather forecast ("70% chance of rain"). A close game might be 55%; a
  mismatch might be 90%.

---

## 5. How to read the results

The project produces a **dashboard** (a web page of charts). Here's how to make sense of each part.

### Team efficiency leaderboard
A ranked list of teams by **EPA per play** — basically "how many expected points does this team add
(offense) or give up (defense) on a typical play?" Higher offense and lower defense = better. The
best teams (e.g., the 2024 national champion) sit at the top. This is a truer ranking than raw
points, because it accounts for *how* teams got their yards.

### RYOE and CPOE leaderboards
The players who most **beat expectations** running and passing. A fun surprise: the top "over
expected" runners are often mobile quarterbacks and option offenses — because defenses don't expect
them to run, they gain more than the situation predicts.

### The "skill vs. luck" plot (stability)
This one answers *"can we even trust this stat?"* We split each player's carries into two halves and
check whether the two halves agree. **If a stat is real skill, the two halves should match** (a good
runner is good in both). If the dots are a loose, shapeless cloud, the stat is mostly **luck** and
shouldn't be taken too seriously. Spoiler: rushing efficiency is *noisy* — which motivates the next
idea.

### Shrinkage (why small samples lie)
Imagine a player carries the ball **5 times** and gains a ton of yards — is he the best runner in
the country, or did he just get a couple of lucky runs? Almost certainly luck. **Shrinkage** is the
math that automatically distrusts small samples: it pulls a 5-carry player's flashy number way back
toward "average," while barely touching a 300-carry workhorse whose number we can trust. On the
chart, the grey dots (raw numbers) fan out wildly for low-usage players; the blue dots (the trusted,
"shrunk" numbers) stay calm until a player has earned our confidence with volume.

> Why so aggressive? The math measured that only about **1%** of the difference in rushing
> efficiency between players is *real, repeatable skill* — the other 99% is situation and chance.
> So it's right to be very skeptical of small samples.

### Team archetypes (personality types)
Every team has a *style* — some are explosive-but-reckless, some grind it out, some are complete on
both sides. The project boils each team's style down and **groups similar teams together**, the way
you might sort music into genres. You'll see clusters like "complete, elite teams," "shootout teams
with great offense but leaky defense," and "up-tempo passing teams." Teams near each other on the
chart play alike.

### The expected-points curve
A simple, satisfying picture: expected points on the y-axis, field position on the x-axis. It slopes
smoothly from about **+6.4 points** at the opponent's goal line down to **negative** when you're
pinned at your own goal line. It just *makes sense* — and that's the point: it confirms our
foundation is sound.

### Is the prediction trustworthy? (the "calibration" chart)
A forecast is only good if it's **honest about its confidence.** This chart checks exactly that: of
all the games where the model said "70% chance," did the home team really win about 70% of the time?
If the dots sit on the diagonal line, the model's confidence is well-calibrated — a "70%" really
means 70%. Ours does.

### The two scorecards: Brier and AUC
Two numbers grade the win-predictor. You don't need the formulas, just the direction:

- **Brier score** — *lower is better.* It punishes being both **wrong** and **overconfident.** Think
  of it as a penalty for bad forecasts.
- **AUC** — *higher is better* (0.5 is a coin flip, 1.0 is perfect). It measures whether the model
  ranks the actual winner above the loser.

### The honesty benchmark: beating Vegas
Here's the part that shows integrity. We compare our predictions against the **betting market** —
the Las Vegas line — which is the gold standard, built from enormous money and information. A model
that *claimed* to crush Vegas would be suspicious. Ours doesn't: it **clearly beats a naive guess**
and gets **very close to the market**, using only on-field performance. Getting close to the best
forecaster in the world is the honest, impressive result — and we report it as-is rather than
cherry-picking a flattering number.

### The "two accountants agree" table
Finally, the dashboard shows the **R-vs-Python check** described earlier: the same models, built
independently in two languages, producing the same answers. It's the project quietly proving its own
math is correct.

---

## 6. So what did we actually learn?

- **The best teams are identifiable by *efficiency*, not just points** — and the rankings match what
  fans saw on the field.
- **Rushing "efficiency" is mostly noise.** Be very skeptical of a running back with a small number
  of carries; the flashy average will probably not last.
- **Mobile quarterbacks quietly beat expectations** as runners, because defenses don't plan for it.
- **On-field efficiency alone can forecast games nearly as well as the betting market** — a strong
  result, honestly reported.

---

## 7. Mini-glossary

- **API** — a way to request data from an online service.
- **Pipeline** — the automated assembly line that moves data from raw to finished.
- **Bronze / Silver / Gold** — raw → cleaned → ready-to-use stages of that line.
- **Model** — a formula that learns patterns from past data to explain or predict.
- **EP / EPA** — expected points / expected points added; the value of a field position, and how
  much a play changed it.
- **RYOE / CPOE** — running / passing performance *compared to what was expected* in the situation.
- **Win probability** — the forecasted percentage chance a team wins.
- **Calibration** — whether a "70%" forecast really comes true about 70% of the time.
- **Brier score / AUC** — grades for a forecast (lower Brier = better; higher AUC = better).
- **Shrinkage** — automatically distrusting small samples by pulling them toward average.
- **Parity check** — proving two independent calculations agree, as a correctness test.

---

## 8. Want to run it yourself?

You'll need some free tools installed (listed in the [`README.md`](README.md)); then a single
command runs everything end-to-end. Even if you never run it, the [dashboard preview images](README.md#dashboard-preview)
in the README show the finished product. Data throughout is courtesy of
**[CollegeFootballData.com](https://collegefootballdata.com)**.
