# Security

## Reporting a vulnerability

Please report a security problem privately, through GitHub's private vulnerability reporting: on the repository page, open the **Security** tab and choose **Report a vulnerability**. Please do not open a public issue or a Discussion for it.

Include what you found, where (file or page), and how to reproduce it. Do not include anyone's personal data. We will reply through the same private report.

## What counts

ME Atlas is a static website and a Python pipeline that runs on the maintainer's own machine. It has no accounts, no database and no payments. Relevant problems are, for example: a secret or key committed to the repository, a way for text in an issue, a pull request or a fetched record to make the pipeline run code or write to `cards/`, or a script injection in the generated site.

A wrong or misleading statement on a card is not a security problem: report it as an error with the issue form, see [CONTRIBUTING.md](CONTRIBUTING.md).
