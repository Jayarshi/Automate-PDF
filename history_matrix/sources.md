# Source reliability manifest

Edit the YAML block below so that every PDF in `books/` has exactly one entry.
Weights are explicit human inputs, not LLM outputs. `credibility_weight` measures
factual reliability from 0 to 1. `independence_factor` discounts sources that
substantially copy or depend on other books (1 means fully independent).

```yaml
sources:
  - id: book_a
    filename: book_a.pdf
    title: "Book A: Primary Chronicle"
    author: "Example Author"
    role: primary
    credibility_weight: 1.0
    independence_factor: 1.0
    description: "Gold-standard primary source for dated events and named participants."
    bias_notes: "Written by an institutional participant; weaker on opponents' motives."

  - id: book_b
    filename: book_b.pdf
    title: "Book B: Contextual History"
    author: "Example Historian"
    role: secondary
    credibility_weight: 0.75
    independence_factor: 0.9
    description: "Strong synthesis and social context, with extensive citations."
    bias_notes: "Interpretive framing is partisan; factual chronology is generally strong."

  - id: book_c
    filename: book_c.pdf
    title: "Book C: General Survey"
    author: "Example Editor"
    role: tertiary
    credibility_weight: 0.4
    independence_factor: 0.7
    description: "Useful for orientation but often summarizes secondary works."
    bias_notes: "Sparse citations and several known simplifications."
```
