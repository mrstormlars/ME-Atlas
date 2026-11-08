# Excluded hypotheses

Hypotheses the Atlas has left out, with the reason and the sources for it. Founder ruling 2026-11-08 (`docs/pm/DECISIONS.md`): a refuted hypothesis gets no card and is not surveyed, and it is named here with why. The survey counts its MeSH headings in the `refuted` domain of `config/survey_domains.yaml`, so they stay visible in the census without being selected.

Every statement below comes from the cached PubMed record (`data/cache/pubmed/<pmid>.xml`), abstract only. Case definitions were not checked: TODO: verify before any of this text is published on the site.

## XMRV, a mouse-related retrovirus, as a cause of ME/CFS

- **The original finding was retracted.** A 2009 study reported DNA of the retrovirus XMRV in blood cells of 68 of 101 patients and 8 of 218 healthy controls. Its PubMed record is marked as retracted (pmid:19815723). The cache also holds a notice of partial retraction (pmid:21998366).
- **The original investigators did not find it in a blinded test.** A multicentre blinded analysis of blood from 147 patients and 146 healthy subjects, by the investigators who described the original association, found no evidence of XMRV or of the related polytropic murine leukemia virus (pmid:22991430).
- **A blinded multi-site prospective study found no difference.** Mouse retroviral DNA was detected in 5 of 72 patients and 2 of 37 healthy subjects, with no difference between the groups; the authors read the sequences as coming from the PCR reagents (pmid:25092471).

Census headings moved to the `refuted` domain: Xenotropic murine leukemia virus-related virus; Retroviridae Infections; Leukemia Virus, Murine; Gammaretrovirus. "Tumor Virus Infections" stays in the `infection` domain, because its records include Epstein-Barr virus studies.
