import { Autocomplete } from "@mantine/core";

interface AutocompleteInputProps {
  value: string;
  suggestions: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  style?: React.CSSProperties;
}

export default function AutocompleteInput({ value, suggestions, onChange, placeholder, style }: AutocompleteInputProps) {
  return (
    <Autocomplete
      value={value}
      onChange={onChange}
      data={suggestions}
      placeholder={placeholder}
      style={style}
      onOptionSubmit={onChange}
    />
  );
}
