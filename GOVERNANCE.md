# Governance

This project is preparing a proposal to the Open Mainframe Project Technical Advisory Council. Until that proposal is accepted, the rules in this file are how the repository is run.

## Technical Charter

TODO: once the Open Mainframe Project accepts this project, replace this paragraph with a link to the project's OMP technical charter. Do not copy the charter into this repository. No charter URL exists yet, and this file does not invent one.

## Roles

### Contributor

A contributor sends issues, discussions, or pull requests. A merged contribution does not by itself grant write access.

### Maintainer

A maintainer reviews changes, merges pull requests, cuts releases, and votes on the decisions below. The current maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md).

There is no Technical Steering Committee yet. If the project is accepted by the Open Mainframe Project, the technical charter will define that body. Until then, maintainers collectively cover those duties.

## Promotion

A current maintainer nominates a contributor by opening an issue or a pull request that proposes the change to [MAINTAINERS.md](MAINTAINERS.md). The nomination states what the person has contributed.

Promotion uses the vote in the next section. The new maintainer must have two-factor authentication enabled on their GitHub account before write access is granted.

Removing a maintainer uses the same documented vote.

## Decisions and voting

Routine changes, including code review, use lazy consensus. A change is accepted when a maintainer approves it and no maintainer objects. An objection blocks the change until it is resolved or a vote is taken.

A contested decision, a change to this file, and any grant or removal of write access require a majority of the current maintainers. Each maintainer has one vote. The vote is recorded in the pull request or issue that proposes the change, including who voted and the outcome. Silence is not a vote. A maintainer who does not vote within 7 days is not counted, and the majority is of the votes cast, with at least two maintainers voting when more than one maintainer exists. With a single maintainer, that maintainer's recorded decision is the vote.

## Write access

Write access is granted only to maintainers. It is not granted to someone who does not hold that role.

The grant is the documented maintainer vote above. The repository owner must keep GitHub's requirement that everyone with write access has two-factor authentication enabled. A maintainer who disables two-factor authentication loses write access until it is turned back on.

GitHub teams are the preferred way to map the maintainer role to write access once the project has more than one maintainer.

## Releases

Releases follow [RELEASE.md](RELEASE.md).

## Meetings

There are no regular maintainer or community meetings. If a series starts, a maintainer announces the schedule, how to join, and where agendas and notes will live in [GitHub Discussions](https://github.com/ca6iya/zvm-otel-exporter/discussions), and adds that information to the Meetings section of [README.md](README.md).
