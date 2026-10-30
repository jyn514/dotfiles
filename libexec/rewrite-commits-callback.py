if (
    commit.author_name == b"jyn"
    and commit.author_email == b"github@jyn.dev"
    and commit.committer_email == b"breq@jyn.dev"
):
    commit.author_name = commit.committer_name
    commit.author_email = commit.committer_email
    commit.committer_name = b"jyn"
    commit.committer_email = b"github@jyn.dev"
