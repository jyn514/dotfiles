if isinteractive()
    using InteractiveUtils
    InteractiveUtils.define_editor("hx-hax", wait=true) do cmd, path, line, column
        `$cmd $path:$line:$column`
    end
end
