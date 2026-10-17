$(function () {
    var PREVIEW_DELAY = 300;
    var MAX_LISTED = 20;

    var openModal = $("#maintenance").data("open-modal");
    if (openModal) {
        var target = {"add": "#add-maintenance-modal", "start-now": "#start-now-modal"}[openModal];
        $(target || "#" + openModal).modal("show");
    }

    var tagsData = document.getElementById("mw-all-tags");
    var allTags = tagsData ? JSON.parse(tagsData.textContent) : [];
    $(".maintenance-modal .mw-tags").each(function () {
        new TomSelect(this, {
            create: true,
            createOnBlur: true,
            delimiter: " ",
            diacritics: false,
            hideSelected: true,
            highlight: false,
            labelField: "value",
            options: allTags.map(function (tag) { return {value: tag}; }),
            refreshThrottle: 0,
            render: {no_results: (data, escape) => ""},
            searchField: ["value"],
        });
    });

    function showPreview($preview, doc) {
        $preview.empty().removeClass("warning");
        if (doc.count == 0) {
            $preview.addClass("warning").text(
                "No checks have all of these tags right now. " +
                "The window will still apply to checks that get these tags later.");
            return;
        }

        $preview.append($("<div>").text("Covers " + doc.count + " checks right now:"));
        var $list = $("<ul>");
        doc.checks.forEach(function (check) {
            $list.append($("<li>").append($("<a>").text(check.name).attr("href", check.url)));
        });
        $preview.append($list);
        if (doc.count > MAX_LISTED) {
            $preview.append($("<div>").text("and " + (doc.count - MAX_LISTED) + " more"));
        }
    }

    function updatePreview($form) {
        var $preview = $form.find(".maintenance-preview");
        var scope = $form.find("input[name=scope]:checked").val();
        var tags = $form.find("input[name=tags]").val();
        if (scope == "tags" && !tags.trim()) {
            $preview.empty().removeClass("warning");
            return;
        }

        $preview.removeClass("warning").text("Checking which checks this covers…");
        var requestId = ($form.data("preview-request") || 0) + 1;
        $form.data("preview-request", requestId);
        $.ajax({
            url: $form.data("preview-url"),
            data: {scope: scope, tags: tags},
            success: function (doc) {
                // Ignore responses that arrive after a newer request was sent
                if ($form.data("preview-request") == requestId) {
                    showPreview($preview, doc);
                }
            },
            error: function () {
                if ($form.data("preview-request") == requestId) {
                    $preview.removeClass("warning").text(
                        "Could not load the preview. You can still save the window.");
                }
            }
        });
    }

    function schedulePreview($form) {
        clearTimeout($form.data("preview-timer"));
        $form.data("preview-timer", setTimeout(function () {
            updatePreview($form);
        }, PREVIEW_DELAY));
    }

    $(".maintenance-modal").on("shown.bs.modal", function () {
        updatePreview($(this).find("form"));
    });

    $(".maintenance-modal input[name=scope]").on("change", function () {
        var $form = $(this).closest("form");
        $form.removeClass("scope-all scope-tags").addClass("scope-" + this.value);
        schedulePreview($form);
    });

    $(".maintenance-modal input[name=tags]").on("change", function () {
        schedulePreview($(this).closest("form"));
    });

    $(".mw-presets button").on("click", function () {
        var $group = $(this).closest(".mw-presets");
        $group.find("button").removeClass("active").attr("aria-pressed", "false");
        $(this).addClass("active").attr("aria-pressed", "true");
        $("#mw-now-duration").val($(this).data("minutes"));
    });

    $("#mw-now-duration").on("input", function () {
        var value = this.value;
        $(".mw-presets button").each(function () {
            var match = String($(this).data("minutes")) === value;
            $(this).toggleClass("active", match).attr("aria-pressed", match ? "true" : "false");
        });
    });

    $(document).on("submit", ".maintenance-modal form, form.mw-confirm", function () {
        var $button = $(this).find("button[type=submit]");
        $button.prop("disabled", true).text($button.data("pending-text"));
    });
});
