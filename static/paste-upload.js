(function () {
    function buildFileList(files) {
        const dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f); });
        return dt.files;
    }

    function addPreview(file, input, previews) {
        if (!previews) return;
        const wrapper = document.createElement("span");
        wrapper.className = "attachment-preview";

        if (file.type.indexOf("image") === 0) {
            const img = document.createElement("img");
            img.src = URL.createObjectURL(file);
            wrapper.appendChild(img);
        }

        const name = document.createElement("span");
        name.textContent = file.name;
        wrapper.appendChild(name);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-attachment";
        remove.textContent = "✕";
        remove.addEventListener("click", function () {
            const remaining = Array.from(input.files).filter(function (f) { return f !== file; });
            input.files = buildFileList(remaining);
            wrapper.remove();
        });
        wrapper.appendChild(remove);

        previews.appendChild(wrapper);
    }

    function setupPasteZone(zone) {
        const input = zone.querySelector('input[type="file"]');
        const previews = zone.querySelector(".attachment-previews");
        if (!input) return;

        zone.addEventListener("paste", function (event) {
            const items = event.clipboardData ? event.clipboardData.items : [];
            for (const item of items) {
                if (item.type.indexOf("image") !== 0) continue;
                const file = item.getAsFile();
                if (!file) continue;

                const ext = (file.type.split("/")[1] || "png").toLowerCase();
                const named = new File([file], "screenshot-" + Date.now() + "." + ext, { type: file.type });
                input.files = buildFileList(Array.from(input.files).concat(named));
                addPreview(named, input, previews);
                event.preventDefault();
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".paste-zone").forEach(setupPasteZone);
    });
})();
