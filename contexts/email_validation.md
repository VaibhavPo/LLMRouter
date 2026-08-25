### Problem Statement

The UserSchema in our application currently lacks email format validation and
phone number validation. This allows invalid data to enter the database, causing
downstream bugs in notification systems that assume valid email/phone formats.

For example:
- Email validation is missing: "not-an-email" is accepted
- Phone validation is missing: "123" is accepted (should be 10 digits)
- No feedback to users about what makes a valid email/phone

This must be fixed before the next release.

### Functional Requirements

1. **Email Validation**
   - Must validate format according to RFC 5322 (or practical subset)
   - Must reject common invalid patterns: missing @, missing domain, etc.
   - Should accept common valid patterns: firstname.lastname@company.co.uk, etc.
   - Should be optional field (can be empty/null)

2. **Phone Validation**
   - Must validate US phone format: 10 digits (with or without formatting)
   - Accept formats: 1234567890, (123) 456-7890, 123-456-7890
   - Reject invalid: too short, too long, non-numeric
   - Should be optional field (can be empty/null)

3. **Error Messages**
   - When validation fails, return clear error message (not just "invalid")
   - Examples:
     - "Email must contain @ symbol"
     - "Phone must be 10 digits"

4. **No Breaking Changes**
   - Existing valid data should still be valid
   - Migration: backfill invalid data or warn users

### Assumptions

- We're using Pydantic v2 for the schema
- Email can be validated with simple regex (not full RFC 5322 parser)
- Phone is US-only format
- Validation happens at model level (not database level)
- Test suite exists and is running (pytest)
- Git is available for version control

### Shared Vocabulary

- **UserSchema:** Pydantic BaseModel in `src/models/user.py`
- **Validation:** Checking data format using Pydantic validators before database save
- **TDD:** Test-Driven Development approach (write tests first, implement after)
- **Pydantic Validator:** A function decorated with `@field_validator` that checks field value
- **Optional:** In Pydantic, means the field can be None or missing

### Current Implementation

**UserSchema** (src/models/user.py):
```python
from pydantic import BaseModel, Field

class UserSchema(BaseModel):
    id: int
    name: str
    email: Optional[str] = None  # No validation
    phone: Optional[str] = None  # No validation
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Tests** (tests/test_models/test_user.py):
- 12 existing tests for basic functionality
- No tests for email/phone validation

**Related Code:**
- `src/validators.py` - Some custom validators exist (e.g. name length, password strength)
- `src/utils/phone.py` - Has a `format_phone()` function for display (could reuse)
- Database: PostgreSQL with email/phone columns (varchar)

### Relevant Files

1. `src/models/user.py` - UserSchema definition (30 lines)
2. `tests/test_models/test_user.py` - Existing tests (45 lines)
3. `src/validators.py` - Custom validators library (100 lines)
4. `src/utils/phone.py` - Phone formatting utility (20 lines)
5. `docs/schema.md` - Current schema documentation (needs update)

### Tech Stack

- **Language:** Python 3.10+
- **Framework:** FastAPI (uses Pydantic)
- **ORM:** SQLAlchemy
- **Database:** PostgreSQL
- **Testing:** pytest, pytest-cov
- **Validation:** Pydantic v2
- **Version Control:** Git

### Design Constraints

1. **Performance:** Validation must run in <1ms per field
2. **Compatibility:** Must work with existing ORM (SQLAlchemy)
3. **Testability:** Should be unit-testable without database
4. **Documentation:** Schema validation rules must be auto-discoverable

### Acceptance Criteria

- ✅ Email validation rejects invalid formats
- ✅ Phone validation rejects invalid lengths
- ✅ Both fields remain optional
- ✅ Error messages are clear and actionable
- ✅ All tests pass (including new tests)
- ✅ Code coverage >90%
- ✅ Linter passes (ruff, mypy)
- ✅ No breaking changes to existing API
- ✅ Documentation updated
- ✅ One commit with clear message

### Change Log

- **2024-01-15 10:30 UTC** — Initial context created
  - Analyzed UserSchema validation gap
  - Defined requirements for email/phone validation
  - Identified affected files and test locations
