# History Matrix — Source Registry and Research Protocol

## 1. Purpose

This project is a source-grounded historical fact matrix for research on the Russian Revolution of 1917, Bolshevism, the post-revolutionary crisis, the rise of bureaucracy, and the subsequent degeneration of the international revolutionary movement.

The immediate research target is:

> **Chapter 2 — The Russian Revolution of 1917**

The larger book will eventually cover:

1. Bolshevism and the crisis of the Second International.
2. The Russian Revolution of 1917.
3. Permanent Revolution and the historical lessons of 1917.
4. Civil War, Brest-Litovsk, Poland, isolation, and the post-revolutionary crisis.
5. Kronstadt, NEP, Workers' Opposition, and the crisis of the isolated workers' state.
6. Bureaucracy and Lenin's struggle against it.
7. Socialism in One Country.
8. The international struggle against fascism and the degeneration of the Third International.

The system must therefore preserve **historical evidence separately from political interpretation**. It must never assume that a Stalinist, Trotskyist, liberal, or other later interpretation is true merely because it is stated by an authoritative author.

---

# 2. Core Research Principle

This project is **not a conventional RAG question-answering system**.

The objective is to construct an auditable historical ledger:

```text
PDF corpus
    ↓
OCR / text extraction with page metadata
    ↓
Atomic historical claims
    ↓
Entity and event normalization
    ↓
Cross-source alignment
    ↓
Support / contradiction / silence classification
    ↓
Evidence-quality assessment
    ↓
Human-auditable fact matrix
    ↓
Historical synthesis
```

The system must never generate a historical conclusion merely because one retrieved passage sounds plausible.

For every important claim, the system should be able to answer:

- Which source makes the claim?
- On what page?
- Is the source contemporary, participant, archival, or retrospective?
- Does another source independently support it?
- Does another source contradict it?
- Is the apparent contradiction genuine, or merely a difference in terminology or chronology?
- Is the source describing an observation, reporting somebody else's statement, or offering an interpretation?
- Is the evidence first-hand?
- Is the claim explicitly documented or inferred?
- What remains uncertain?

---

# 3. Source Corpus

The current corpus is:

```text
books/
├── alexander-rabinowitch-the-bolsheviks-come-to-power-the-revolution-of-1917-in-petrograd.pdf
├── [Book] History of the Bolshevik Party_ Bolshevism - The Road ....pdf
├── hrr-vol1.pdf
├── hrr-vol2.pdf
├── hrr-vol3.pdf
├── kamenev_i_zinovev_v_1917_g._fakty_i_dokumenty.pdf
├── lenin-cw-vol-23.pdf
├── lenin-cw-vol-24.pdf
├── lenin-cw-vol-25.pdf
├── lenin-cw-vol-26.pdf
├── March 1917 editorials on the war by Kamenev and Stalin.pdf
├── Six-Red-Months-in-Russia.pdf
├── ten-days-that-shook-the-world-reed.pdf
├── The-Bolshevik-Revolution-vol-One.pdf
└── the-russian-revolution-1917-a-personal-record.pdf
```

The exact bibliographic metadata of a PDF must be extracted from the PDF itself where possible. A filename is not sufficient evidence for author, edition, translator, publication year, or pagination.

---

# 4. Source Identities

Use stable source IDs rather than filenames alone.

| Source ID | File | Author / Work | Historical function |
|---|---|---|---|
| `RABINOWITCH_1917` | `alexander-rabinowitch-the-bolsheviks-come-to-power-the-revolution-of-1917-in-petrograd.pdf` | Alexander Rabinowitch, *The Bolsheviks Come to Power* | Modern scholarly reconstruction of Petrograd in 1917; Gold Standard source for historical facts. Credibility 100% |
| `WOODS_BOLSHEVISM` | `[Book] History of the Bolshevik Party_ Bolshevism - The Road ....pdf` | Alan Woods / corresponding work; verify bibliographic metadata from PDF | Modern Trotskyist interpretation; useful as an interpretation and for locating arguments, secondary source, credibility 50-60% |
| `TROTSKY_HRR_I` | `hrr-vol1.pdf` | Leon Trotsky, *History of the Russian Revolution*, Vol. I | Participant's retrospective interpretation; especially useful for social dynamics, political chronology, class forces, and revolutionary interpretation. ~80% credibility, but with personal bias |
| `TROTSKY_HRR_II` | `hrr-vol2.pdf` | Leon Trotsky, *History of the Russian Revolution*, Vol. II | Participant's retrospective interpretation; especially useful for social dynamics, political chronology, class forces, and revolutionary interpretation. ~80% credibility, but with personal bias; particularly relevant to July, Kornilov, September–October and the insurrection |
| `TROTSKY_HRR_III` | `hrr-vol3.pdf` | Leon Trotsky, *History of the Russian Revolution*, Vol. III | Participant's retrospective interpretation; especially useful for social dynamics, political chronology, class forces, and revolutionary interpretation. ~80% credibility, but with personal bias |
| `KAMENEV_ZINOVIEV_1917` | `kamenev_i_zinovev_v_1917_g._fakty_i_dokumenty.pdf` | Collection concerning Kamenev and Zinoviev in 1917; verify editor/edition | Documentary source for Kamenev and Zinoviev's conduct and the 1917 controversies. Primary source, politically dubious |
| `LENIN_CW_23` | `lenin-cw-vol-23.pdf` | V. I. Lenin, *Collected Works*, Vol. 23 | Primary writings and correspondence; exact edition/page metadata must be retained |
| `LENIN_CW_24` | `lenin-cw-vol-24.pdf` | V. I. Lenin, *Collected Works*, Vol. 24 | Primary writings and correspondence |
| `LENIN_CW_25` | `lenin-cw-vol-25.pdf` | V. I. Lenin, *Collected Works*, Vol. 25 | Primary writings and correspondence; especially relevant to late 1917 |
| `LENIN_CW_26` | `lenin-cw-vol-26.pdf` | V. I. Lenin, *Collected Works*, Vol. 26 | Primary writings and correspondence; use according to the edition's chronological coverage |
| `KAMENEV_STALIN_PRAVDA_MARCH_1917` | `March 1917 editorials on the war by Kamenev and Stalin.pdf` | Kamenev and Stalin, March 1917 *Pravda* editorials | Primary contemporary evidence for Bolshevik policy before Lenin's return and for Kamenev/Stalin's public positions. Primary source, politically dubious |
| `BRYANT_1917` | `Six-Red-Months-in-Russia.pdf` | Louise Bryant, *Six Red Months in Russia* | Contemporary eyewitness/reportage; useful for atmosphere, events and perceptions, but must be distinguished from documentary evidence as it is secondary hearing too. credibility 70-75% |
| `REED_10_DAYS` | `ten-days-that-shook-the-world-reed.pdf` | John Reed, *Ten Days That Shook the World* | Contemporary eyewitness/reportage; highly valuable for atmosphere and participant testimony, but individual anecdotes and reconstructed scenes require corroboration as it is secondary hearing too. credibility 70-75% |
| `CARR_BOLSHEVIK_REVOLUTION_I` | `The-Bolshevik-Revolution-vol-One.pdf` | E. H. Carr, *The Bolshevik Revolution 1917–1923*, Vol. I | Major historical reconstruction; important for institutional, political, constitutional and organisational history. credibility 100% |
| `SUKHANOV_1917` | `the-russian-revolution-1917-a-personal-record.pdf` | Nikolai Sukhanov, *The Russian Revolution 1917: A Personal Record* | Contemporary observer record; particularly valuable for political atmosphere, meetings, personalities and chronology, while requiring awareness of Sukhanov's position and retrospective editing. as it is primary observation based, but biased. credibility 90-95%  |

---

# 5. Source Independence

**Independence matters more than source count.**

Five books repeating the same claim do not constitute five independent confirmations if four derive from one earlier interpretation.

The pipeline should therefore distinguish:

```text
independent_support
dependent_support
same-source-repetition
```

For example:

```text
Trotsky → Alan Woods
```

is not two independent confirmations.

Likewise:

```text
Lenin primary document
        +
Rabinowitch independent reconstruction
        +
Sukhanov contemporary account
```

is substantially stronger corroboration.

The database should record known or suspected source dependence whenever it can be established.

---

# 6. Historical Claim Ontology

Atomic extraction should represent claims at the smallest useful historical level.

A claim should normally contain:

```json
{
  "fact_id": "temp_000001",
  "event": "April Crisis",
  "date_start": "1917-04-20",
  "date_end": "1917-04-21",
  "location": "Petrograd",
  "subject": "Pavel Milyukov",
  "predicate": "stated",
  "object_or_detail": "Russia would continue the war in accordance with the Allied commitments",
  "claim_type": "political_statement",
  "evidence_class": "E1",
  "quote_excerpt": "...",
  "source_id": "SOURCE_ID",
  "source_page": 123,
  "source_location": "PDF page / printed page / chapter if available",
  "firsthand_status": "direct_document",
  "confidence_before_alignment": "unassessed"
}
```

Do not force every historical statement into a simple subject-predicate-object form if that loses essential chronology or context. The schema should permit:

- events,
- actions,
- statements,
- votes,
- appointments,
- institutional changes,
- numerical claims,
- causal claims,
- interpretations,
- reported speech.

---

# 7. Atomic Fact Extraction Rules

Stage 1 must process each book independently.

Never provide all books to the extraction model simultaneously.

Recommended process:

```text
PDF
 ↓
OCR / text extraction
 ↓
page-preserving clean text
 ↓
2,000–3,000 token windows
 ↓
small overlap
 ↓
structured extraction
 ↓
raw fact store
```

Every extracted fact must retain:

- source ID,
- PDF page,
- printed page if distinguishable,
- chapter/section,
- paragraph or text location where possible,
- exact quote excerpt when useful,
- whether the statement is direct observation, reported speech, or author interpretation.

The extractor must **not** reconcile contradictions.

For example, if one source says:

> 10 voted for and 2 against

and another source gives a different sequence, Stage 1 records both claims independently.

Reconciliation belongs to Stage 3.

---

# 8. Quotation Protocol

Direct quotation is subject to a stricter standard than paraphrase.

A quotation may be used in the final manuscript only when:

1. The exact wording is present in the source.
2. The relevant page is verified.
3. The edition/translation is recorded.
4. The quotation is not reconstructed from memory.
5. Ellipses do not alter the meaning.
6. The quotation is clearly attributed.
7. If the wording comes from a translation, the translation is identified where relevant.

Never generate a quotation merely because it sounds like something the historical actor would have said.

Never use quotation marks for a paraphrase.

For a disputed quotation, preserve the exact source wording and flag it for manual verification.

Preferred record:

```json
{
  "quote": "exact verified wording",
  "source_id": "LENIN_CW_24",
  "page": 42,
  "quote_type": "direct",
  "translation_status": "published_translation",
  "verification": "page_verified"
}
```

---

# 9. Paraphrase Protocol

Paraphrase is preferred when the exact wording is not necessary.

A paraphrase must preserve:

- actor,
- action,
- date,
- object,
- context,
- degree of certainty.

Do not strengthen language.

Examples:

Bad:

> Lenin proved that the Provisional Government was doomed.

Better:

> Lenin argued that the Provisional Government could not resolve the central contradictions of the revolution and urged the Bolsheviks to prepare for a transfer of power to the soviets.

The second formulation distinguishes Lenin's argument from the historian's conclusion.

---

# 10. Claim Classification

Every important extracted claim should receive one of the following:

```text
FACT_ESTABLISHED
FACT_PROBABLE
FACT_PLAUSIBLE
FACT_CONTESTED
FACT_UNVERIFIED
INTERPRETATION
CAUSAL_INTERPRETATION
SOURCE_REPORT
```

Definitions:

### FACT_ESTABLISHED

Strongly supported by contemporary documentary evidence and/or multiple independent sources, with no serious contradictory evidence.

### FACT_PROBABLE

Strong evidence exists, but the evidence is incomplete or partly dependent.

### FACT_PLAUSIBLE

An authentic source makes the claim, but independent corroboration is weak or absent.

### FACT_CONTESTED

Credible sources disagree materially.

### FACT_UNVERIFIED

The claim may be genuine but presently lacks sufficient evidence.

### INTERPRETATION

An author's explanation, characterization, or political interpretation rather than a directly verifiable event.

### CAUSAL_INTERPRETATION

A claim connecting events causally. These require particular caution.

### SOURCE_REPORT

A source reports that another person said/did something. This must not automatically be treated as evidence that the reported event occurred.

---

# 11. Silence / Omission

**Silence is not contradiction.**

This is a critical rule.

If Rabinowitch discusses October but does not mention a particular Trotsky anecdote, this must be recorded as:

```text
SILENT
```

not:

```text
CONTRADICTION
```

A source can only be marked contradictory when it explicitly provides incompatible evidence.

Distinguish:

```text
SUPPORT
IMPLICIT_SUPPORT
SILENT
EXPLICIT_CONTRADICTION
```

Also distinguish between:

```text
NOT_COVERED
COVERED_BUT_SILENT
```

The latter can sometimes be historiographically informative, but it is still not a contradiction.

---

# 12. Cross-Referencing Protocol

Stage 3 operates on each canonical fact.

For every canonical fact:

1. Identify all sources that discuss the event.
2. Locate relevant passages in each source.
3. Classify each source's stance.
4. Preserve exact supporting or contradictory passages.
5. Determine whether the sources are independent.
6. Record differences in chronology, terminology, scope, or interpretation.
7. Only then produce a synthesis.

Example:

```text
Canonical Fact:
Kamenev and Zinoviev opposed the decision to prepare an armed insurrection.

RABINOWITCH_1917:
Explicit support.

LENIN_CW_24:
Explicit support.

KAMENEV_ZINOVIEV_1917:
Primary evidence requiring contextual reading.

TROTSKY_HRR_II:
Explicit support, with retrospective interpretation.

REED_10_DAYS:
Related narrative; specific anecdote separately assessed.

BRYANT_1917:
Silent / not covered.

WOODS_BOLSHEVISM:
Derivative interpretation; not independent corroboration.
```

---

# 13. Source Weighting

The project may use numerical weights, but **weights must not be treated as truth probabilities**.

A source is not "1.0 reliable" in every domain.

For example:

- Lenin is excellent evidence of what Lenin wrote, but not automatically of whether his prediction was correct.
- Sukhanov is valuable evidence of what Sukhanov observed, but not automatically of what happened outside his access.
- Trotsky is valuable for his recollection and interpretation, but his political self-positioning must be considered.
- Rabinowitch is valuable for scholarly reconstruction, but his conclusions remain historical interpretations.

Therefore weights should be multidimensional where possible:

```text
source_authority
firsthand_access
temporal_proximity
documentary_basis
independence
specialist_expertise
political_bias_risk
```

Do not reduce these immediately to one number.

If a single numerical score is required for sorting, it must be treated as a **research-priority score**, not a probability that the claim is true.

---

# 14. Recommended Stance Values

For computational aggregation:

```text
+1.0  EXPLICIT_SUPPORT
+0.5  IMPLICIT_OR_CIRCUMSTANTIAL_SUPPORT
 0.0  SILENT
-1.5  EXPLICIT_CONTRADICTION
```

However, the database must preserve the underlying categorical stance.

Never let the number replace the evidence.

The raw score should therefore be accompanied by:

```text
supporting_sources
contradicting_sources
silent_sources
independent_support_count
dependent_support_count
primary_document_count
eyewitness_count
scholarly_reconstruction_count
```

---

# 15. Revised Confidence Scoring

The original numerical model is useful as a heuristic, but the project must not equate source agreement with historical truth.

Use the following conceptual tiers:

### Tier 1 — Established

Typical conditions:

- contemporary documentary evidence, or
- multiple genuinely independent sources,
- no serious contradictory evidence,
- chronology and context are consistent.

### Tier 2 — Probable

Typical conditions:

- strong source evidence,
- but incomplete independent corroboration,
- or some uncertainty concerning chronology/details.

### Tier 3 — Plausible / Unverified

Typical conditions:

- authentic source makes the claim,
- but independent corroboration is absent or weak,
- and there is no decisive contradiction.

### Tier 4 — Contested

Credible sources materially disagree.

The database must state the disagreement rather than force a numerical winner.

### Tier 5 — Unsupported / Speculative

Insufficient evidence to use the claim as established history.

---

# 16. Special Rule for Political Claims

Claims concerning the motives of Lenin, Trotsky, Stalin, Kamenev, Zinoviev, Bukharin, Kerensky, Martov, etc. require special treatment.

Separate:

```text
observable_action
documented_statement
reported_motive
historian_inference
```

For example:

```text
Observable:
Kamenev published an article in Pravda.

Documented:
The article argued for a particular policy.

Inference:
Kamenev was attempting to restrain the revolutionary movement.

Motive claim:
Kamenev wanted to prevent the revolution from proceeding toward socialism.
```

The last claim requires substantially more evidence than the first two.

Never convert inferred motive into fact.

---

# 17. Special Rule for Sukhanov

Sukhanov is especially valuable for:

- political atmosphere,
- meetings,
- contemporary perceptions,
- personalities,
- chronology,
- the non-Bolshevik socialist milieu.

But his political position and access must be considered.

Do not treat Sukhanov's interpretation as neutral simply because he is hostile to Bolshevism.

Extract his observations and interpretations separately.

---

# 18. Special Rule for Alan Woods

The Woods volume is useful for:

- identifying Trotskyist interpretations,
- locating political arguments,
- identifying claims that require verification,
- understanding later Trotskyist historiography.

It must not be counted as independent evidence merely because it agrees with Trotsky.

For the historical matrix:

```text
Trotsky + Woods
```

should normally count as:

```text
one interpretive tradition
```

unless Woods supplies independent documentary evidence.

---

# 19. Chapter 2 Research Taxonomy

The Chapter 2 event/entity taxonomy is:

```text
CH2_1917
├── PRE_REVOLUTION
│   ├── WAR
│   ├── ECONOMY
│   ├── STATE_CRISIS
│   ├── WORKERS
│   ├── PEASANTS
│   ├── SOLDIERS
│   └── POLITICAL_PARTIES
│
├── FEBRUARY
│   ├── WOMENS_DEMONSTRATIONS
│   ├── STRIKES
│   ├── GARRISON_MUTINY
│   ├── TSARIST_COLLAPSE
│   └── PETROGRAD_SOVIET
│
├── DUAL_POWER
│   ├── PROVISIONAL_GOVERNMENT
│   ├── PETROGRAD_SOVIET
│   ├── ORDER_NO_1
│   ├── BOLSHEVIKS
│   ├── MENSHEVIKS
│   ├── SOCIALIST_REVOLUTIONARIES
│   └── PRAVDA
│
├── APRIL
│   ├── LENIN_RETURN
│   ├── APRIL_THESES
│   ├── BOLSHEVIK_DEBATE
│   ├── KAMENEV
│   ├── STALIN
│   └── APRIL_CRISIS
│
├── MEZHRAIONTSY
│   ├── ORIGIN
│   ├── PARTY_UNITY
│   ├── TROTSKY
│   ├── ZIMMERWALD
│   └── RETURN
│
├── JUNE_JULY
│   ├── COALITION
│   ├── JUNE_OFFENSIVE
│   ├── BOLSHEVIK_GROWTH
│   ├── WORKERS
│   ├── SOLDIERS
│   ├── SPONTANEITY
│   └── REPRESSION
│
├── KORNILOV
│   ├── KORNILOV
│   ├── KERENSKY
│   ├── LENIN_UNDERGROUND
│   ├── TROTSKY_ARREST
│   ├── COUNTER_REVOLUTION
│   ├── BOLSHEVIK_DEFENCE
│   ├── MEZHRAIONTSY_MERGER
│   └── AUGUST_CONGRESS
│
├── BOLSHEVIK_MAJORITIES
│   ├── PETROGRAD_SOVIET
│   ├── MOSCOW_SOVIET
│   ├── TROTSKY_CHAIRMAN
│   ├── WORKERS
│   ├── SOLDIERS
│   └── PROVISIONAL_GOVERNMENT_CRISIS
│
├── INSURRECTION_DEBATE
│   ├── LENIN_LETTERS
│   ├── CENTRAL_COMMITTEE
│   ├── KAMENEV
│   ├── ZINOVIEV
│   ├── TROTSKY
│   ├── STALIN
│   └── FINAL_DECISION
│
├── OCTOBER
│   ├── STRATEGIC_POINTS
│   ├── SMOLNY
│   ├── LENIN
│   ├── TROTSKY
│   ├── MRC
│   ├── PETROGRAD_SOVIET
│   ├── WORKERS
│   ├── SOLDIERS
│   ├── BOLSHEVIK_ORGANISATION
│   └── WINTER_PALACE
│
└── SECOND_CONGRESS
    ├── MENSHEVIK_WALKOUT
    ├── SR_WALKOUT
    ├── SOVIET_GOVERNMENT
    ├── DECREE_ON_PEACE
    ├── DECREE_ON_LAND
    └── HISTORICAL_SIGNIFICANCE
```

---

# 20. Required Entities

The extraction system should normalize recurring people and organizations.

At minimum:

```text
Lenin
Trotsky
Stalin
Kamenev
Zinoviev
Bukharin
Martov
Plekhanov
Kerensky
Kornilov
Kollontai
Sukhanov
Milyukov
Chernov
Dan
Tsereteli
Sverdlov
Dzerzhinsky
Stalin
```

Organizations:

```text
Bolshevik Party
Mensheviks
Mezhraiontsy
Socialist Revolutionaries
Left SRs
Petrograd Soviet
Moscow Soviet
Provisional Government
Military Revolutionary Committee
Second Congress of Soviets
Central Committee
```

Do not merge people with similar names without contextual verification.

---

# 21. Date Normalization

Russian events may appear under Old Style and New Style dates.

The database must preserve the source's original date and, where possible, store a normalized date separately.

Example:

```json
{
  "date_source": "25 October 1917",
  "calendar": "Old Style",
  "date_normalized": "1917-11-07",
  "normalized_calendar": "Gregorian"
}
```

Never silently change the date printed in a historical source.

---

# 22. Numerical Claims

Numerical claims require special handling.

Examples:

- vote counts,
- delegate numbers,
- troop numbers,
- casualties,
- factory employment,
- election results,
- percentages.

Store:

```text
reported_value
unit
source
page
date
scope
method
```

Do not average conflicting historical numbers automatically.

A source reporting 10,000 troops and another 12,000 may be using different definitions or dates.

---

# 23. Contradiction Taxonomy

Not every difference is a contradiction.

Classify disagreements as:

```text
D1 — Genuine factual contradiction
D2 — Different date / chronology
D3 — Different scope
D4 — Different terminology
D5 — Different perspective
D6 — Interpretation disagreement
D7 — Numerical discrepancy
D8 — Source-access limitation
D9 — Translation / edition difference
```

Only D1 should automatically receive a contradiction penalty.

---

# 24. Causal Claims

Causal claims require higher standards than event claims.

For example:

> The Kornilov Affair caused the Bolsheviks to gain majority support.

This is not a simple fact.

The database should break it into:

1. Kornilov Affair occurred.
2. Bolsheviks participated in defence.
3. Bolshevik membership/support increased afterward.
4. Soviet election results changed.
5. Contemporary actors attributed the change to Kornilov.
6. Later historians explain the change partly through Kornilov.

Then the causal proposition can be assessed.

---

# 25. Absence of Evidence

The system must never reason:

> Source does not mention X → X did not happen.

Instead:

```text
absence_of_evidence
```

is recorded separately.

A negative historical claim such as:

> "No one proposed insurrection before date X."

requires a much more comprehensive documentary search.

---

# 26. Search Strategy

Search queries should be event-centered and source-centered.

Examples:

```text
"April Theses" Lenin Kamenev Stalin
"March Pravda" Kamenev Stalin
"Mezhraiontsy" Trotsky 1917
"August Congress" Trotsky Mezhraiontsy
"July Days" Bolsheviks
"Kornilov" Bolsheviks Trotsky Lenin
"Petrograd Soviet" majority Bolsheviks
"October insurrection" Central Committee Kamenev Zinoviev
"Military Revolutionary Committee" Trotsky
"Second Congress of Soviets" October 1917
```

When searching a source, search both:

- exact names,
- event terminology,
- alternative transliterations.

For Russian names, preserve normalized canonical names while retaining source spellings in quotations.

---

# 27. Stage 2 — Entity and Event Deduplication

The deduplicator must distinguish:

```text
same event
same claim
related event
same person
same organization
same political tendency
```

Do not merge two claims merely because they concern the same event.

Example:

```text
"Trotsky chaired the MRC."

"Trotsky personally planned every military operation."

```

These are not the same fact.

The first may be documentary.

The second is a much stronger causal claim.

---

# 28. Canonical Fact Construction

A canonical fact should be minimally interpretive.

Bad:

```text
Trotsky masterminded the October Revolution.
```

Better:

```text
Trotsky chaired the Military Revolutionary Committee during the October seizure of power.
```

Then separately evaluate:

```text
Trotsky's operational importance
```

This prevents the canonical fact itself from embedding the conclusion.

---

# 29. Stage 3 — Alignment

For every canonical fact, create a matrix:

| Source | Coverage | Stance | Evidence Type | Page | Independence | Notes |
|---|---|---|---|---|---|---|
| Rabinowitch | Covered | Support | E4 | p. X | Independent | ... |
| Carr | Covered | Support | E4 | p. X | Partly dependent | ... |
| Trotsky | Covered | Support | E3 | p. X | Participant | ... |
| Lenin | Covered | Support | E1 | p. X | Primary | ... |
| Sukhanov | Covered | Silent | E2 | — | Independent | ... |
| Reed | Covered | Support | E2 | p. X | Independent | ... |

This matrix is the primary audit trail.

---

# 30. Stage 4 — Scoring

A possible research score is:

\[
R(F)=\sum_i W_i S_i
\]

with:

```text
+1.0 = explicit support
+0.5 = implicit/circumstantial support
 0.0 = silence
-1.5 = explicit contradiction
```

But the score must be supplemented by evidence metadata.

Do not report:

> "The claim has an 83% probability of being true."

That would falsely imply a calibrated probabilistic model.

Instead report:

> "High-confidence / independently corroborated"

or:

> "Plausible but single-source"

or:

> "Contested"

The numerical score is for ranking and triage, not for pretending to quantify historical truth.

---

# 31. Independence-Aware Scoring

Where possible, prevent double counting.

Example:

```text
Trotsky = 1 supporting tradition
Woods = derivative of Trotsky = 0 additional independent support
```

If five sources independently reconstruct the same event from different evidence, their support can contribute separately.

The scoring engine should therefore maintain:

```text
independent_cluster_id
```

for source traditions.

---

# 32. The "Myth Detection" Rule

When a later historical narrative makes a strong claim, classify it into:

```text
DOCUMENTED
SUPPORTED
PARTIALLY_SUPPORTED
EXAGGERATED
DISTORTED
FALSE
UNVERIFIED
```

Do not use "falsification" merely because a claim is politically biased.

A claim should be called falsification only when there is sufficient evidence that the historical representation materially departs from the evidence.

---

# 33. Important Distinction: Error vs Distortion vs Falsification

Use these terms carefully.

### Historical error

A source gives an incorrect fact, possibly through memory or incomplete information.

### Distortion

A source selectively presents true facts in a way that materially changes their historical significance.

### Falsification

A historical representation knowingly or systematically replaces documentary evidence with a materially false account.

Intent should not be inferred without evidence.

For example:

```text
Incorrect chronology ≠ automatically falsification.
Selective omission ≠ automatically falsification.
Political interpretation ≠ automatically falsification.
```

---

# 35. Final Fact Ledger

The final database should be capable of producing:

| Fact ID | Event | Canonical Fact | Supporting Sources | Contradicting Sources | Silent Sources | Evidence Class | Independence | Confidence | Notes |
|---|---|---|---|---|---|---|---|---|---|
| F0001 | February | ... | ... | ... | ... | E1/E2/E3/E4 | ... | Tier 1 | ... |
| F0002 | April | ... | ... | ... | ... | ... | ... | Tier 2 | ... |

The ledger is more important than the final
<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->
 score.

---

# 36. Minimum Audit Requirement

No major historical claim should enter the final manuscript unless the researcher can retrieve:

```text
claim
→ source
→ page
→ relevant passage
→ evidence type
→ corroboration status
→ contradiction status
→ confidence assessment
```

If any component is missing, flag the claim.

Do not silently fill the missing information.

---

# 36. Hallucination Prevention

The system must follow these hard rules:

```text
NEVER invent a quotation.
NEVER invent a page number.
NEVER invent a source.
NEVER infer a document's content from its filename.
NEVER treat a paraphrase as a quotation.
NEVER treat silence as contradiction.
NEVER count derivative sources as independent corroboration.
NEVER turn an author's interpretation into an established fact.
NEVER infer motive from an action without evidence.
NEVER silently resolve contradictory sources.
NEVER fabricate archival evidence.
NEVER claim a source was consulted when it was not.
```

If evidence is unavailable:

```text
NOT VERIFIED
```

is the correct output.

---

# 38. Research Philosophy

The ultimate objective is not to prove a predetermined political thesis.

The objective is:

> **Reconstruct what can be established about the historical process, distinguish evidence from interpretation, identify where later narratives distort that process, and only then draw political lessons.**

If the evidence supports a claim associated with Trotsky, retain it.

If the evidence contradicts Trotsky, record the contradiction.

If the evidence supports a claim made by Stalinist historiography, retain it.

If Stalinist historiography is contradicted by primary evidence, demonstrate the contradiction.

If the evidence is insufficient, preserve the uncertainty.

The historical matrix must be capable of producing conclusions that are **more cautious than the politics of any individual source**.

That is the principal safeguard against reproducing the very falsification the project is intended to investigate.

---

# 51. Executable Mathematical Policy

The following block converts this protocol into reproducible inputs. Values are
research priors in `[0,1]`, not probabilities that a source is true. The source
quality term is a weighted geometric mean; dependence is additionally controlled
by `independence_cluster_id`, so several derivative books cannot multiply the same
tradition's contribution.

<!-- HISTORY_MATRIX_CONFIG_START -->
```yaml
version: 2
project: {title: "Chapter 2 — The Russian Revolution of 1917", taxonomy_root: CH2_1917}
scoring:
  dimension_weights:
    source_authority: 0.20
    firsthand_access: 0.15
    temporal_proximity: 0.10
    documentary_basis: 0.20
    independence: 0.15
    specialist_expertise: 0.10
    bias_safety: 0.10
  evidence_class_multipliers:
    E1_DIRECT_DOCUMENT: 1.00
    E2_CONTEMPORARY_EYEWITNESS: 0.90
    E3_PARTICIPANT_RETROSPECTIVE: 0.78
    E4_SCHOLARLY_RECONSTRUCTION: 0.82
    E5_DERIVATIVE_INTERPRETATION: 0.45
    E6_REPORTED_SPEECH: 0.60
    E7_UNKNOWN: 0.35
  stance_values:
    explicit_support: 1.0
    implicit_support: 0.5
    explicit_contradiction: -1.5
    mixed: 0.0
    silent: 0.0
  contradiction_penalty_types: [D1_FACTUAL]
  tier_thresholds:
    meaningful_contribution: 0.20
    serious_contradiction: 0.45
    established_support_mass: 1.20
    established_independent_clusters: 2
    probable_support_mass: 0.65
    probable_independent_clusters: 1
    plausible_support_mass: 0.20

presets:
  trotsky: &trotsky
    role: participant
    evidence_class_default: E3_PARTICIPANT_RETROSPECTIVE
    independence_cluster_id: TROTSKYIST_HRR_TRADITION
    source_authority: 0.82
    firsthand_access: 0.90
    temporal_proximity: 0.75
    documentary_basis: 0.78
    independence: 0.65
    specialist_expertise: 0.92
    political_bias_risk: 0.55
    description: "Participant retrospective account."
    bias_notes: "High access; separate observation from retrospective political framing."
  lenin: &lenin
    author: "V. I. Lenin"
    role: primary
    evidence_class_default: E1_DIRECT_DOCUMENT
    independence_cluster_id: LENIN_COLLECTED_WORKS
    source_authority: 0.92
    firsthand_access: 0.98
    temporal_proximity: 1.00
    documentary_basis: 1.00
    independence: 0.90
    specialist_expertise: 0.88
    political_bias_risk: 0.60
    description: "Primary writings and correspondence."
    bias_notes: "Direct evidence of Lenin's words, not automatic proof of external events."

sources:
  - id: RABINOWITCH_1917
    filename: alexander-rabinowitch-the-bolsheviks-come-to-power-the-revolution-of-1917-in-petrograd.pdf
    title: "The Bolsheviks Come to Power"
    author: "Alexander Rabinowitch"
    role: secondary
    evidence_class_default: E4_SCHOLARLY_RECONSTRUCTION
    independence_cluster_id: RABINOWITCH_SCHOLARLY
    source_authority: 1.00
    firsthand_access: 0.25
    temporal_proximity: 0.35
    documentary_basis: 0.98
    independence: 1.00
    specialist_expertise: 1.00
    political_bias_risk: 0.15
    description: "Gold-standard modern scholarly reconstruction of Petrograd in 1917."
    bias_notes: "Conclusions remain interpretations and must be evidence-linked."

  - id: WOODS_BOLSHEVISM
    filename: "[Book] History of the Bolshevik Party_ Bolshevism - The Road ....pdf"
    title: "Bolshevism: The Road to Revolution"
    author: "Alan Woods"
    role: secondary
    evidence_class_default: E5_DERIVATIVE_INTERPRETATION
    independence_cluster_id: TROTSKYIST_HRR_TRADITION
    source_authority: 0.55
    firsthand_access: 0.10
    temporal_proximity: 0.20
    documentary_basis: 0.55
    independence: 0.20
    specialist_expertise: 0.65
    political_bias_risk: 0.70
    description: "Later Trotskyist interpretation useful for locating arguments."
    bias_notes: "Normally derivative of Trotsky, not an independent confirmation."

  - {id: TROTSKY_HRR_I, filename: hrr-vol1.pdf, title: "History of the Russian Revolution, Vol. I", author: "Leon Trotsky", <<: *trotsky}
  - {id: TROTSKY_HRR_II, filename: hrr-vol2.pdf, title: "History of the Russian Revolution, Vol. II", author: "Leon Trotsky", <<: *trotsky}
  - {id: TROTSKY_HRR_III, filename: hrr-vol3.pdf, title: "History of the Russian Revolution, Vol. III", author: "Leon Trotsky", <<: *trotsky}

  - id: KAMENEV_ZINOVIEV_1917
    filename: kamenev_i_zinovev_v_1917_g._fakty_i_dokumenty.pdf
    title: "Kamenev and Zinoviev in 1917: Facts and Documents"
    author: null
    role: documentary_collection
    evidence_class_default: E1_DIRECT_DOCUMENT
    independence_cluster_id: KAMENEV_ZINOVIEV_DOCUMENTS
    source_authority: 0.78
    firsthand_access: 0.88
    temporal_proximity: 0.88
    documentary_basis: 0.92
    independence: 0.75
    specialist_expertise: 0.72
    political_bias_risk: 0.65
    description: "Document collection concerning Kamenev and Zinoviev in 1917."
    bias_notes: "Editor, provenance, and political selection require verification."

  - {id: LENIN_CW_23, filename: lenin-cw-vol-23.pdf, title: "Collected Works, Vol. 23", <<: *lenin}
  - {id: LENIN_CW_24, filename: lenin-cw-vol-24.pdf, title: "Collected Works, Vol. 24", <<: *lenin}
  - {id: LENIN_CW_25, filename: lenin-cw-vol-25.pdf, title: "Collected Works, Vol. 25", <<: *lenin}
  - {id: LENIN_CW_26, filename: lenin-cw-vol-26.pdf, title: "Collected Works, Vol. 26", <<: *lenin}

  - id: KAMENEV_STALIN_PRAVDA_MARCH_1917
    filename: March 1917 editorials on the war by Kamenev and Stalin.pdf
    title: "March 1917 Pravda Editorials on the War"
    author: "Lev Kamenev and Joseph Stalin"
    role: primary
    evidence_class_default: E1_DIRECT_DOCUMENT
    independence_cluster_id: PRAVDA_MARCH_1917_DOCUMENTS
    source_authority: 0.90
    firsthand_access: 0.98
    temporal_proximity: 1.00
    documentary_basis: 0.98
    independence: 0.90
    specialist_expertise: 0.80
    political_bias_risk: 0.70
    description: "Contemporary primary evidence of public policy positions."
    bias_notes: "Strong evidence for published positions, not private motives."

  - id: BRYANT_1917
    filename: Six-Red-Months-in-Russia.pdf
    title: "Six Red Months in Russia"
    author: "Louise Bryant"
    role: eyewitness
    evidence_class_default: E2_CONTEMPORARY_EYEWITNESS
    independence_cluster_id: BRYANT_EYEWITNESS
    source_authority: 0.74
    firsthand_access: 0.86
    temporal_proximity: 0.96
    documentary_basis: 0.58
    independence: 0.90
    specialist_expertise: 0.65
    political_bias_risk: 0.42
    description: "Contemporary eyewitness and reportage."
    bias_notes: "Separate direct observation from hearsay and reconstructed dialogue."

  - id: REED_10_DAYS
    filename: ten-days-that-shook-the-world-reed.pdf
    title: "Ten Days That Shook the World"
    author: "John Reed"
    role: eyewitness
    evidence_class_default: E2_CONTEMPORARY_EYEWITNESS
    independence_cluster_id: REED_EYEWITNESS
    source_authority: 0.76
    firsthand_access: 0.88
    temporal_proximity: 0.97
    documentary_basis: 0.62
    independence: 0.90
    specialist_expertise: 0.68
    political_bias_risk: 0.48
    description: "Contemporary eyewitness account and participant testimony."
    bias_notes: "Anecdotes and reconstructed scenes need corroboration."

  - id: CARR_BOLSHEVIK_REVOLUTION_I
    filename: The-Bolshevik-Revolution-vol-One.pdf
    title: "The Bolshevik Revolution 1917–1923, Vol. I"
    author: "E. H. Carr"
    role: secondary
    evidence_class_default: E4_SCHOLARLY_RECONSTRUCTION
    independence_cluster_id: CARR_SCHOLARLY
    source_authority: 0.96
    firsthand_access: 0.20
    temporal_proximity: 0.42
    documentary_basis: 0.96
    independence: 0.92
    specialist_expertise: 0.96
    political_bias_risk: 0.25
    description: "Major institutional and political scholarly reconstruction."
    bias_notes: "High documentary value; conclusions remain interpretations."

  - id: SUKHANOV_1917
    filename: the-russian-revolution-1917-a-personal-record.pdf
    title: "The Russian Revolution 1917: A Personal Record"
    author: "Nikolai Sukhanov"
    role: eyewitness
    evidence_class_default: E2_CONTEMPORARY_EYEWITNESS
    independence_cluster_id: SUKHANOV_EYEWITNESS
    source_authority: 0.93
    firsthand_access: 0.92
    temporal_proximity: 0.92
    documentary_basis: 0.75
    independence: 0.96
    specialist_expertise: 0.88
    political_bias_risk: 0.52
    description: "Contemporary observer record of atmosphere, meetings, and chronology."
    bias_notes: "Separate observation from hostile interpretation and retrospective editing."
```
<!-- HISTORY_MATRIX_CONFIG_END -->
