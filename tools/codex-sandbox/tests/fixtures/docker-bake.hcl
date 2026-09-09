target "base" {
  context = "."
  dockerfile = "base.Dockerfile"
}

target "proxy" {
  context = "."
  dockerfile = "proxy.Dockerfile"
  args = { BASE_IMAGE = "sandbox-base" }
  contexts = { sandbox-base = "target:base" }
}
