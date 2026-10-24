use std::path::PathBuf;
use tic_proxy::client::normalize;
fn a(a: &[&str]) -> Vec<String> {
    a.iter().map(|s| (*s).into()).collect()
}
#[test]
fn native_parser_proves_exact_file_replacement_not_virtual_index_mapping() {
    let cases: &[(&[&str], &[&str], &str)] = &[
        (
            &["edit", "-F", "draft.md"],
            &["edit", "-F", "-"],
            "draft.md",
        ),
        (&["edit", "-Fdraft.md"], &["edit", "-F-"], "draft.md"),
        (
            &["edit", "--file=draft.md"],
            &["edit", "--file=-"],
            "draft.md",
        ),
        (&["new", "-cFdraft.md"], &["new", "-cF-"], "draft.md"),
        (
            &["new", "-c", "-Fdraft.md", "-aowner"],
            &["new", "-c", "-F-", "-aowner"],
            "draft.md",
        ),
        (
            &["new", "-cF", "draft.md"],
            &["new", "-cF", "-"],
            "draft.md",
        ),
        // Option-looking data before actual file option; never replace the data.
        (
            &["new", "--comment=-Fcanary", "-Fcanary"],
            &["new", "--comment=-Fcanary", "-F-"],
            "canary",
        ),
        (
            &["new", "--comment=--file=canary", "--file=canary"],
            &["new", "--comment=--file=canary", "--file=-"],
            "canary",
        ),
        (
            &["new", "--comment", "canary", "-Fcanary"],
            &["new", "--comment", "canary", "-F-"],
            "canary",
        ),
        (
            &["new", "--comment=-Fcanary", "-cFcanary"],
            &["new", "--comment=-Fcanary", "-cF-"],
            "canary",
        ),
        (
            &["edit", "-Fcanary", "--", "-Fcanary"],
            &["edit", "-F-", "--", "-Fcanary"],
            "canary",
        ),
        (
            &["edit", "--file=-Fcanary"],
            &["edit", "--file=-"],
            "-Fcanary",
        ),
        (
            &["edit", "--file=--file=canary"],
            &["edit", "--file=-"],
            "--file=canary",
        ),
        (&["edit", "-F", "./-"], &["edit", "-F", "-"], "./-"),
        (
            &["meta", "field", "-Frelative/guest-only"],
            &["meta", "field", "-F-"],
            "relative/guest-only",
        ),
        (&["spec", "-F", "draft"], &["spec", "-F", "-"], "draft"),
        (
            &["writeup", "new", "--title=-Fdraft", "-Fdraft"],
            &["writeup", "new", "--title=-Fdraft", "-F-"],
            "draft",
        ),
        (
            &["writeup", "edit", "-Fdraft", "--", "-Fdraft"],
            &["writeup", "edit", "-F-", "--", "-Fdraft"],
            "draft",
        ),
    ];
    for &(input, expected, path) in cases {
        let (actual, file) = normalize(&a(input)).unwrap_or_else(|e| panic!("{input:?}: {e}"));
        assert_eq!(actual, a(expected), "{input:?}");
        assert_eq!(file, Some(PathBuf::from(path)));
    }
}
#[test]
fn text_and_double_dash_are_not_file_grammars() {
    for input in [
        vec![],
        vec!["new", "--title=-Fguest"],
        vec!["comment", "--", "-Fguest"],
        vec!["spec", "--", "--file=guest"],
        vec!["writeup", "edit", "id", "--body=-Fguest"],
        vec!["writeup", "new", "-t", "title", "--body", "guest"],
        vec!["--help"],
        vec!["ls"],
    ] {
        assert_eq!(
            normalize(&a(&input)).unwrap(),
            (a(&input), None),
            "{input:?}"
        );
    }
    assert_eq!(
        normalize(&a(&["edit", "-F-"])).unwrap(),
        (a(&["edit", "-F-"]), Some("-".into()))
    );
    assert!(normalize(&a(&["comment", "-e", "text"])).is_err());
}

#[test]
fn generated_spelling_data_order_product_preserves_every_nonfile_operand() {
    // Exhaustive bounded product, not rejection-heavy random whole-argv input:
    // four native spellings x seven path classes x three data disguises x two
    // orders. Concrete failures print the entire input for direct replay.
    let paths = [
        "draft",
        "space name",
        "雪",
        "-Fother",
        "--file=other",
        "./-",
        "line\nbreak",
    ];
    let spellings = ["-F", "--file=", "-cF", "-cF="];
    let mut count = 0;
    for path in paths {
        for spelling in spellings {
            for disguise in [
                path.to_string(),
                format!("-F{path}"),
                format!("--file={path}"),
            ] {
                for file_first in [false, true] {
                    let data = format!("--comment={disguise}");
                    let file = format!("{spelling}{path}");
                    let replacement = format!("{spelling}-");
                    let (input, expected) = if file_first {
                        (
                            vec!["new".to_string(), file, data.clone()],
                            vec!["new".to_string(), replacement, data],
                        )
                    } else {
                        (
                            vec!["new".to_string(), data.clone(), file],
                            vec!["new".to_string(), data, replacement],
                        )
                    };
                    let (actual, collected) =
                        normalize(&input).unwrap_or_else(|e| panic!("{input:?}: {e}"));
                    assert_eq!(actual, expected, "{input:?}");
                    assert_eq!(collected, Some(PathBuf::from(path)), "{input:?}");
                    assert_eq!(
                        normalize(&actual).unwrap().0,
                        actual,
                        "idempotence: {input:?}"
                    );
                    count += 1;
                }
            }
        }
    }
    assert_eq!(count, 168); // Every declared class and interaction ran, no filtering.
}
