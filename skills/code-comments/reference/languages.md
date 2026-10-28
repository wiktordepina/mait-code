# Language conventions

Per-language shape for the rules in `SKILL.md`. The project's own convention
wins over anything here (SKILL.md Rule 1). Use this when the project has no
established style, or as a check that the style you found is being applied
properly.

Every example here obeys Rule 2 (no history), Rule 3 (no ephemeral facts) and
Rule 7 (ASCII only). The prose in them is the point, not just the syntax.

## Python

**Three flavours in the wild.** Detect, do not assume. Google style is the
greenfield default: it reads as plain text in an editor, and both mkdocstrings
and Sphinx napoleon consume it.

Google:

```python
def assume_role(role_arn: str, session_name: str, duration: int = 3600) -> Credentials:
    """Exchange the current identity for temporary credentials.

    Args:
        role_arn: Full ARN. A bare role name will not resolve across accounts.
        session_name: Appears in CloudTrail as the principal, so it wants to
            identify the caller, not the role.
        duration: Seconds. Capped by the role's own MaxSessionDuration, which
            can be lower than this default.

    Returns:
        Credentials expiring at the granted duration, which may be shorter
        than requested.

    Raises:
        AccessDenied: Trust policy rejects the caller, or the requested
            duration exceeds the role's maximum.
    """
```

Sphinx / reST:

```python
def assume_role(role_arn: str, session_name: str, duration: int = 3600) -> Credentials:
    """Exchange the current identity for temporary credentials.

    :param role_arn: Full ARN. A bare role name will not resolve across accounts.
    :param session_name: Appears in CloudTrail as the principal.
    :param duration: Seconds. Capped by the role's own MaxSessionDuration.
    :returns: Credentials expiring at the granted duration, which may be
        shorter than requested.
    :raises AccessDenied: Trust policy rejects the caller.
    """
```

NumPy:

```python
def assume_role(role_arn, session_name, duration=3600):
    """Exchange the current identity for temporary credentials.

    Parameters
    ----------
    role_arn : str
        Full ARN. A bare role name will not resolve across accounts.
    duration : int
        Seconds. Capped by the role's own MaxSessionDuration.

    Returns
    -------
    Credentials
        Expiring at the granted duration, which may be shorter than requested.
    """
```

**Python specifics:**

* Type hints are the type documentation. Do not restate them in prose. NumPy
  style duplicates types by design, so if the project uses it, keep the types
  in the docstring consistent with the annotations or drop the annotations.
* One-line docstrings stay on one line, with the closing quotes on the same
  line. A summary plus sections gets a blank line after the summary.
* Modules get a docstring when the module's purpose is not obvious from its
  name and its exports. Do not write one that just says the filename.
* Classes: document the class's role and any invariant it maintains. Document
  attributes in the class docstring, not with a comment per assignment.
  `__init__` params go wherever the project's convention puts them, and never
  in both places.
* `@property` gets a one-line docstring at most, and none if the name is
  honest. A property with a full Returns section is usually a method.
* Dataclasses and Pydantic models: field names and types carry it. Comment
  only fields with a non-obvious unit, encoding, or a name that misleads.
* Test functions: the name is the documentation. `test_assume_role_rejects_
  expired_token` needs no docstring. Add one only where the setup is subtle
  enough that a reader cannot see what is being asserted.
* Do not comment above a decorator to explain what the decorator does.

## Go

Godoc, not sections. Doc comments are prose and start with the identifier's
name. This is a hard convention in Go, do not import Args:/Returns: into it.

```go
// AssumeRole exchanges the current identity for temporary credentials valid
// for duration. The granted lifetime can be shorter than requested: the
// role's own MaxSessionDuration takes precedence. sessionName appears in
// CloudTrail as the principal, so it should identify the caller.
//
// It returns an *AccessDeniedError if the trust policy rejects the caller.
func AssumeRole(ctx context.Context, roleARN, sessionName string, duration time.Duration) (*Credentials, error) {
```

**Go specifics:**

* Start with the identifier: `// AssumeRole exchanges...`, not `// This
  function exchanges...`.
* Full sentences, full stops. Blank `//` line between paragraphs.
* Every exported identifier gets a doc comment: funcs, types, consts, vars,
  and the package. Unexported ones get one when the behaviour is non-obvious.
* Package comment goes in one file only, conventionally `doc.go` for anything
  substantial: `// Package billing prices orders and issues invoices.`
* Document the error conditions a caller branches on, in prose. Do not
  enumerate every wrapped error.
* Document what is safe for concurrent use. Absence of a note reads as unsafe
  to careful callers, so say it when a type is goroutine-safe.
* Comment a naked `return` or an ignored error (`_ = f.Close()`) with why.
* Struct fields: short trailing or preceding comments for units, encodings and
  optionality. Tags carry the serialisation, so do not restate them.
* `// nolint:` and `//go:` directives are machine instructions, not comments.
  Keep them separate from doc comments and put a human comment above them
  explaining why the lint is suppressed.

## Shell

Scripts get a header block. This is the one place a longer block is right:
shell has no signature, so the interface has to be written down.

```bash
#!/usr/bin/env bash
#
# Rotate the deploy role's external ID across every account in the org.
#
# Usage:
#   rotate-external-id.sh <account-file> [--dry-run]
#
# Arguments:
#   account-file  One account id per line. Blank lines and # comments skipped.
#   --dry-run     Print the intended changes without calling STS.
#
# Environment:
#   AWS_PROFILE   Must resolve to a role with org-wide iam:UpdateRole.
#   ROTATION_TTL  Seconds before the previous id stops being accepted.
#                 Defaults to 86400.
#
# Exit codes:
#   0  All accounts rotated.
#   1  Usage error.
#   2  At least one account failed. Successful ones are not rolled back.
```

**Shell specifics:**

* Functions get a short block covering globals read or written, arguments
  positionally, and the exit or return meaning if it is not just success and
  failure. Shell's implicit globals are exactly the kind of thing a reader
  cannot see, so name them.
* Comment `set -euo pipefail` deviations. If a command is deliberately allowed
  to fail (`|| true`), say why.
* Comment non-obvious quoting, subshell and word-splitting decisions. These
  look like mistakes to a careful reader.
* Do not comment what a standard pipeline does. Do comment why an unusual flag
  is there: `# --no-paginate: the CI runner has no TTY and paging hangs it`.
* Trailing comments on flag-heavy commands are good. Keep them to one line.

## Terraform and HCL

The `description` field is the documentation and is not optional. Comments are
for wiring a reader cannot infer from the resource graph.

```hcl
variable "retention_days" {
  # 400 is the ceiling the log group's own quota allows without a support case
  type        = number
  default     = 30
  description = "CloudWatch retention for the task's logs. Values above 400 are rejected at apply time."
}

resource "aws_iam_role_policy_attachment" "ecs_exec" {
  # attached separately rather than inlined: inline policies on this role are
  # managed by the platform module and get overwritten on its apply
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.ecs_exec.arn
}
```

**HCL specifics:**

* Every `variable` and `output` gets a `description`. Say the constraint and
  the unit, not the type.
* Use `#`, not `//`, for consistency with the wider ecosystem.
* Comment explicit `depends_on`, `lifecycle` blocks, `ignore_changes` and
  `count`/`for_each` expressions that are not self-evident. These exist
  precisely because the obvious behaviour was wrong, so the reason is the
  valuable part.
* Do not comment above a resource to name it. `# create the S3 bucket` above
  `resource "aws_s3_bucket"` is noise.
* Module blocks: comment a pinned version only when the pin is deliberate and
  the reason is not "latest at the time". "Latest at the time" is Rule 3.

## YAML

Ansible, Kubernetes, CI pipelines, compose files. Task and step `name` fields
do the describing, so a comment repeating a name is pure duplication.

```yaml
- name: Install the CloudWatch agent
  # rpm rather than the ansible package module: the vendor repo is not
  # signed with a key the base image trusts
  ansible.builtin.command:
    cmd: rpm -Uvh --nodigest {{ agent_url }}
  register: agent_install
  changed_when: agent_install.rc == 0
```

**YAML specifics:**

* Write real `name` values first. Reach for a comment only when the reason is
  not sayable in a name.
* Comment ordering dependencies that the file's structure does not show, and
  anchors or aliases whose effect is remote from their definition.
* Comment a value that must stay in step with something outside the file, and
  name that thing.
* Do not comment indentation, structure or the schema itself.
* Kubernetes manifests: annotations that drive controller behaviour are
  invisible magic to most readers. Comment what consumes them.

## SQL

```sql
-- customers with at least one order in the window, one row per customer
-- the self join is on (customer_id, created_at) because order_id is only
-- unique per shard
select ...
```

* Comment the intent of a CTE at its definition, in one line. A long query is
  a sequence of named steps and the names plus one line each make it readable.
* Comment joins whose cardinality is surprising, and any join that can
  duplicate rows.
* Comment a hint, index nudge or deliberately un-sargable predicate.
* Do not translate the SQL into English. `-- select the users` above a select
  from users is noise.

## JavaScript and TypeScript

* TypeScript types are the parameter documentation. JSDoc `@param {string}` in
  a `.ts` file is duplication that goes stale. Use a prose JSDoc summary and
  add `@param` lines only where a name and type do not cover the meaning.
* Plain JavaScript with no types: full JSDoc with `@param` and `@returns` is
  appropriate, since nothing else records the shape.
* Comment `await` omissions, deliberate floating promises, and anything
  relying on event loop ordering.
* Comment non-obvious `useEffect` dependency arrays and why an exhaustive-deps
  suppression is correct.
* Do not comment imports, and do not write a banner comment per section of a
  component.
