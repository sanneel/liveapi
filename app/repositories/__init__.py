"""
Repository layer — all DB queries live here.

Keeping queries out of route handlers and models makes them:
  - easy to test in isolation
  - easy to swap (e.g. add caching, switch DB)
  - easy to reason about (one place per table)
"""
