target "base" {
  context = ".agents/sandbox"
  dockerfile = "Dockerfile"
  tags = ["dotfiles-sandbox-base:local"]
}
