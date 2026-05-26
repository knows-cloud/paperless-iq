import { useState } from "react";
import { Autocomplete } from "@mantine/core";

interface TagInputProps {
  allTags: string[];
  placeholder?: string;
  onAdd: (tag: string) => void;
}

export default function TagInput({ allTags, placeholder, onAdd }: TagInputProps) {
  const [value, setValue] = useState("");

  const commit = (tag: string) => {
    const trimmed = tag.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setValue("");
  };

  return (
    <Autocomplete
      value={value}
      onChange={setValue}
      data={allTags}
      placeholder={placeholder ?? "Add tag…"}
      onOptionSubmit={opt => commit(opt)}
      onKeyDown={e => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit(value);
        }
      }}
    />
  );
}
