type InputFieldProps = {
  value: string;
  disabled?: boolean;
  placeholder: string;
  onChange(value: string): void;
  onBlur?(): void;
  onEnter?(): void;
};

export function InputField({
  value,
  disabled = false,
  placeholder,
  onChange,
  onBlur,
  onEnter
}: InputFieldProps) {
  return (
    <input
      className="input"
      disabled={disabled}
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onBlur={() => onBlur?.()}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          onEnter?.();
        }
      }}
    />
  );
}
