# Failure Mode Categories

Use when one suspect path stalls and you need competing hypotheses. Generate 2-3 hypotheses from different categories, test independently, compare evidence.

## Logic

- Incorrect conditional (wrong operator, missing case)
- Off-by-one in loop or array access
- Missing edge case handling
- Incorrect algorithm implementation

## Data

- Invalid or unexpected input
- Type mismatch or coercion error
- Null/None where value expected
- Encoding or serialization problem
- Truncation or overflow

## State

- Race condition between concurrent operations
- Stale cache returning outdated data
- Incorrect initialization or default value
- Unintended mutation of shared state
- State machine transition error

## Integration

- API contract violation (request/response mismatch)
- Version incompatibility between components
- Configuration mismatch between environments
- Missing or incorrect environment variable
- Network timeout or connection failure

## Resource

- Memory leak causing gradual degradation
- Connection pool exhaustion
- File descriptor or handle leak
- Disk space or quota exceeded
- CPU saturation from inefficient processing

## Environment

- Missing runtime dependency
- Wrong library or framework version
- Platform-specific behaviour difference
- Permission or access control issue
- Timezone or locale-related behaviour
